//! Only this app's HWND is subclassed. No game window, process or memory is accessed.
use crate::AppWindow;
use raw_window_handle::{HasWindowHandle, RawWindowHandle};
use slint::{
    ComponentHandle,
    winit_030::{EventResult, WinitWindowAccessor},
};
use std::{cell::RefCell, ffi::c_void, mem::size_of};
use windows::Win32::{
    Foundation::{HWND, LPARAM, LRESULT, RECT, WPARAM},
    Graphics::{Dwm::*, Gdi::*},
    UI::{
        Controls::MARGINS,
        HiDpi::GetDpiForWindow,
        Input::KeyboardAndMouse::{HOT_KEY_MODIFIERS, RegisterHotKey, UnregisterHotKey},
        Shell::{DefSubclassProc, RemoveWindowSubclass, SetWindowSubclass},
        WindowsAndMessaging::*,
    },
};

type HotkeyCallback = Box<dyn Fn(i32)>;

thread_local! {
    static UI: RefCell<Option<slint::Weak<AppWindow>>> = const { RefCell::new(None) };
    static MAIN: std::cell::Cell<isize> = const { std::cell::Cell::new(0) };
    static HOTKEY: RefCell<Option<HotkeyCallback>> = const { RefCell::new(None) };
}

/// The Win32 handle of a Slint window (after it has been shown).
pub(crate) fn hwnd(window: &slint::Window) -> Option<HWND> {
    window
        .with_winit_window(|w| match w.window_handle().ok()?.as_raw() {
            RawWindowHandle::Win32(h) => Some(HWND(h.hwnd.get() as *mut c_void)),
            _ => None,
        })
        .flatten()
}

/// The counter window: no taskbar button, never takes focus, see-through by `opacity` (30–100), and
/// optionally click-through (clicks reach the window underneath).
pub(crate) fn style_overlay(window: &slint::Window, opacity: i64, click_through: bool) {
    let Some(hwnd) = hwnd(window) else { return };
    // SAFETY: plain style and attribute calls on our own window.
    unsafe {
        let mut ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE) as u32
            | WS_EX_LAYERED.0
            | WS_EX_TOOLWINDOW.0
            | WS_EX_NOACTIVATE.0;
        if click_through {
            ex |= WS_EX_TRANSPARENT.0;
        } else {
            ex &= !WS_EX_TRANSPARENT.0;
        }
        SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex as isize);
        let alpha = (opacity.clamp(30, 100) * 255 / 100) as u8;
        let _ = SetLayeredWindowAttributes(
            hwnd,
            windows::Win32::Foundation::COLORREF(0),
            alpha,
            LWA_ALPHA,
        );
    }
}

/// "Ctrl+Alt+F8" -> (RegisterHotKey modifiers, virtual key), as hotkeys.py parses it.
pub(crate) fn parse_hotkey(text: &str) -> Result<(u32, u32), String> {
    let upper = text.to_uppercase().replace(' ', "");
    let parts: Vec<&str> = upper.split('+').collect();
    let (key, modifiers) = parts.split_last().ok_or("Empty hotkey")?;
    let mut flags = 0x4000; // MOD_NOREPEAT
    if modifiers.is_empty() {
        return Err("Hotkeys need Ctrl, Alt, Shift or Win plus a letter, digit or F1–F24".into());
    }
    for m in modifiers {
        flags |= match *m {
            "ALT" => 1,
            "CTRL" => 2,
            "SHIFT" => 4,
            "WIN" => 8,
            _ => {
                return Err(
                    "Hotkeys need Ctrl, Alt, Shift or Win plus a letter, digit or F1–F24".into(),
                );
            }
        };
    }
    let code = match key.strip_prefix('F').and_then(|n| n.parse::<u32>().ok()) {
        Some(n) if (1..=24).contains(&n) => 0x70 + n - 1,
        _ if key.len() == 1 && key.chars().all(|c| c.is_ascii_alphanumeric()) => {
            key.chars().next().map_or(0, |c| c as u32)
        }
        _ => return Err(format!("Unsupported hotkey: {text}")),
    };
    Ok((flags, code))
}

/// Register the global shortcuts on the main window (ids 1..). Badly written ones are an error before
/// anything changes; ones another app owns are skipped and returned.
pub(crate) fn register_hotkeys(
    keys: &[(i32, String)],
    callback: impl Fn(i32) + 'static,
) -> Result<Vec<String>, String> {
    let parsed: Vec<(i32, (u32, u32), &String)> = keys
        .iter()
        .filter(|(_, t)| !t.trim().is_empty())
        .map(|(id, t)| parse_hotkey(t).map(|p| (*id, p, t)))
        .collect::<Result<_, _>>()?;
    let hwnd = HWND(MAIN.with(|m| m.get()) as *mut c_void);
    if hwnd.is_invalid() {
        return Ok(Vec::new());
    }
    let mut busy = Vec::new();
    // SAFETY: registering hotkeys for our own window; WM_HOTKEY arrives in our subclass procedure.
    unsafe {
        for id in 1..=3 {
            let _ = UnregisterHotKey(Some(hwnd), id);
        }
        for (id, (flags, code), text) in parsed {
            if RegisterHotKey(Some(hwnd), id, HOT_KEY_MODIFIERS(flags), code).is_err() {
                busy.push(text.clone());
            }
        }
    }
    HOTKEY.with(|h| *h.borrow_mut() = Some(Box::new(callback)));
    Ok(busy)
}

pub(crate) fn install(ui: &AppWindow) {
    UI.with(|slot| *slot.borrow_mut() = Some(ui.as_weak()));
    let installed = std::rc::Rc::new(std::cell::Cell::new(false));
    ui.window().on_winit_window_event(move |window, event| {
        if let slint::winit_030::winit::event::WindowEvent::Focused(active) = event {
            let active = *active;
            UI.with(|slot| {
                if let Some(ui) = slot.borrow().as_ref().and_then(|w| w.upgrade()) {
                    ui.set_window_active(active); // window controls dim while inactive
                }
            });
        }
        window.with_winit_window(|w| {
            if !installed.replace(true)
                && let Ok(handle) = w.window_handle()
                && let RawWindowHandle::Win32(handle) = handle.as_raw()
            {
                // SAFETY: the handle belongs to this event-loop thread and the subclass is
                // removed at WM_NCDESTROY; no pointer to Rust-owned data crosses the ABI.
                unsafe {
                    decorate(HWND(handle.hwnd.get() as *mut c_void));
                }
            }
            UI.with(|slot| {
                if let Some(ui) = slot.borrow().as_ref().and_then(|w| w.upgrade()) {
                    ui.set_is_maximized(w.is_maximized());
                }
            });
        });
        EventResult::Propagate
    });
}

/// Keep a restored window on a connected monitor: if its title bar would be off every screen, move it to the
/// primary work area. Physical pixels.
pub(crate) fn on_screen(x: i32, y: i32, width: i32, _height: i32) -> (i32, i32) {
    // SAFETY: plain value queries with no retained pointers.
    unsafe {
        let probe = RECT {
            left: x + 40,
            top: y,
            right: x + width - 40,
            bottom: y + 32,
        };
        let monitor = MonitorFromRect(&probe, MONITOR_DEFAULTTONULL);
        if !monitor.is_invalid() {
            return (x, y);
        }
        let primary = MonitorFromPoint(
            windows::Win32::Foundation::POINT { x: 0, y: 0 },
            MONITOR_DEFAULTTOPRIMARY,
        );
        let mut info = MONITORINFO {
            cbSize: size_of::<MONITORINFO>() as u32,
            ..Default::default()
        };
        if GetMonitorInfoW(primary, &mut info).as_bool() {
            return (info.rcWork.left + 40, info.rcWork.top + 40);
        }
        (40, 40)
    }
}

/// Edges where an auto-hiding taskbar sits on this monitor, so a maximized window leaves it 1 px to appear.
unsafe fn autohide_edges(monitor: HMONITOR) -> [bool; 4] {
    use windows::Win32::UI::Shell::{
        ABE_BOTTOM, ABE_LEFT, ABE_RIGHT, ABE_TOP, ABM_GETAUTOHIDEBAREX, ABM_GETSTATE, APPBARDATA,
        SHAppBarMessage,
    };
    unsafe {
        let mut data = APPBARDATA {
            cbSize: size_of::<APPBARDATA>() as u32,
            ..Default::default()
        };
        if SHAppBarMessage(ABM_GETSTATE, &mut data) as u32 & 1 == 0 {
            return [false; 4]; // ABS_AUTOHIDE not set
        }
        let mut info = MONITORINFO {
            cbSize: size_of::<MONITORINFO>() as u32,
            ..Default::default()
        };
        if !GetMonitorInfoW(monitor, &mut info).as_bool() {
            return [false; 4];
        }
        let mut edges = [false; 4];
        for (i, edge) in [ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM]
            .into_iter()
            .enumerate()
        {
            let mut bar = APPBARDATA {
                cbSize: size_of::<APPBARDATA>() as u32,
                uEdge: edge,
                rc: info.rcMonitor,
                ..Default::default()
            };
            edges[i] = SHAppBarMessage(ABM_GETAUTOHIDEBAREX, &mut bar) != 0;
        }
        edges
    }
}

unsafe fn decorate(hwnd: HWND) {
    MAIN.with(|m| m.set(hwnd.0 as isize));
    unsafe {
        let style = GetWindowLongPtrW(hwnd, GWL_STYLE) as u32;
        SetWindowLongPtrW(
            hwnd,
            GWL_STYLE,
            (style
                | WS_THICKFRAME.0
                | WS_CAPTION.0
                | WS_SYSMENU.0
                | WS_MAXIMIZEBOX.0
                | WS_MINIMIZEBOX.0) as isize,
        );
        if !SetWindowSubclass(hwnd, Some(proc), 1, 0).as_bool() {
            return;
        }
        let corner = DWMWCP_ROUND;
        let _ = DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            &corner as *const _ as _,
            size_of::<DWM_WINDOW_CORNER_PREFERENCE>() as u32,
        );
        let margins = MARGINS {
            cxLeftWidth: 1,
            cxRightWidth: 1,
            cyTopHeight: 1,
            cyBottomHeight: 1,
        };
        let _ = DwmExtendFrameIntoClientArea(hwnd, &margins);
        let _ = SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
        );
    }
}

// Physical pixels in, native hit result out. Kept separate so every edge and DPI can be tested.
fn hit(x: i32, y: i32, width: i32, height: i32, scale: f32, maximized: bool) -> u32 {
    let edge = (7.0 * scale).round() as i32;
    if !maximized {
        let left = x < edge;
        let right = x >= width - edge;
        let top = y < edge;
        let bottom = y >= height - edge;
        if top && left {
            return HTTOPLEFT;
        }
        if top && right {
            return HTTOPRIGHT;
        }
        if bottom && left {
            return HTBOTTOMLEFT;
        }
        if bottom && right {
            return HTBOTTOMRIGHT;
        }
        if left {
            return HTLEFT;
        }
        if right {
            return HTRIGHT;
        }
        if top {
            return HTTOP;
        }
        if bottom {
            return HTBOTTOM;
        }
    }
    if y < (32.0 * scale).round() as i32 {
        let button = (46.0 * scale).round() as i32;
        if x >= width - 2 * button && x < width - button {
            return HTMAXBUTTON;
        }
        if x < width - 3 * button {
            return HTCAPTION;
        }
    }
    HTCLIENT
}

unsafe extern "system" fn proc(
    hwnd: HWND,
    message: u32,
    wp: WPARAM,
    lp: LPARAM,
    _: usize,
    _: usize,
) -> LRESULT {
    // SAFETY: Win32 supplies message-specific structs for this synchronous callback. Pointers are
    // used only for their documented message and are never stored after the call.
    unsafe {
        match message {
            WM_NCCALCSIZE if wp.0 != 0 => {
                let params = &mut *(lp.0 as *mut NCCALCSIZE_PARAMS);
                if IsZoomed(hwnd).as_bool() {
                    let monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
                    let mut info = MONITORINFO {
                        cbSize: size_of::<MONITORINFO>() as u32,
                        ..Default::default()
                    };
                    if GetMonitorInfoW(monitor, &mut info).as_bool() {
                        // Maximized windows overhang the screen by the frame; fit the work area exactly.
                        params.rgrc[0] = info.rcWork;
                        let [left, top, right, bottom] = autohide_edges(monitor);
                        if info.rcWork == info.rcMonitor {
                            params.rgrc[0].left += left as i32;
                            params.rgrc[0].top += top as i32;
                            params.rgrc[0].right -= right as i32;
                            params.rgrc[0].bottom -= bottom as i32;
                        }
                    }
                }
                return LRESULT(0);
            }
            WM_NCHITTEST => {
                let mut rect = RECT::default();
                if GetWindowRect(hwnd, &mut rect).is_ok() {
                    let x = lp.0 as i16 as i32 - rect.left;
                    let y = (lp.0 >> 16) as i16 as i32 - rect.top;
                    return LRESULT(hit(
                        x,
                        y,
                        rect.right - rect.left,
                        rect.bottom - rect.top,
                        GetDpiForWindow(hwnd) as f32 / 96.0,
                        IsZoomed(hwnd).as_bool(),
                    ) as isize);
                }
            }
            WM_NCMOUSEMOVE => {
                UI.with(|slot| {
                    if let Some(ui) = slot.borrow().as_ref().and_then(|w| w.upgrade()) {
                        ui.set_max_hover(wp.0 as u32 == HTMAXBUTTON);
                    }
                });
            }
            WM_MOUSEMOVE | WM_NCMOUSELEAVE => {
                UI.with(|slot| {
                    if let Some(ui) = slot.borrow().as_ref().and_then(|w| w.upgrade()) {
                        ui.set_max_hover(false);
                    }
                });
            }
            WM_NCLBUTTONDOWN if wp.0 as u32 == HTMAXBUTTON => {
                return LRESULT(0);
            }
            WM_NCLBUTTONUP if wp.0 as u32 == HTMAXBUTTON => {
                let command = if IsZoomed(hwnd).as_bool() {
                    SC_RESTORE
                } else {
                    SC_MAXIMIZE
                };
                SendMessageW(hwnd, WM_SYSCOMMAND, Some(WPARAM(command as usize)), None);
                return LRESULT(0);
            }
            WM_NCRBUTTONUP if wp.0 as u32 == HTCAPTION => {
                let menu = GetSystemMenu(hwnd, false);
                if !menu.is_invalid() {
                    let x = lp.0 as i16 as i32;
                    let y = (lp.0 >> 16) as i16 as i32;
                    let command = TrackPopupMenu(
                        menu,
                        TPM_RETURNCMD | TPM_RIGHTBUTTON,
                        x,
                        y,
                        None,
                        hwnd,
                        None,
                    );
                    if command.0 != 0 {
                        SendMessageW(hwnd, WM_SYSCOMMAND, Some(WPARAM(command.0 as usize)), None);
                    }
                }
                return LRESULT(0);
            }
            WM_HOTKEY => {
                let id = wp.0 as i32;
                HOTKEY.with(|h| {
                    if let Some(callback) = h.borrow().as_ref() {
                        callback(id);
                    }
                });
                return LRESULT(0);
            }
            WM_NCDESTROY => {
                let _ = RemoveWindowSubclass(hwnd, Some(proc), 1);
            }
            _ => {}
        }
        DefSubclassProc(hwnd, message, wp, lp)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn caption_controls_and_all_resize_edges_at_each_dpi() {
        for scale in [1.0, 1.25, 1.5, 2.0] {
            let w = (1200.0 * scale) as i32;
            let h = (800.0 * scale) as i32;
            for (x, y, want) in [
                (1, 1, HTTOPLEFT),
                (w - 1, 1, HTTOPRIGHT),
                (1, h - 1, HTBOTTOMLEFT),
                (w - 1, h - 1, HTBOTTOMRIGHT),
                (1, h / 2, HTLEFT),
                (w - 1, h / 2, HTRIGHT),
                (w / 2, 1, HTTOP),
                (w / 2, h - 1, HTBOTTOM),
            ] {
                assert_eq!(hit(x, y, w, h, scale, false), want);
            }
            assert_eq!(
                hit(w / 2, (16.0 * scale) as i32, w, h, scale, false),
                HTCAPTION
            );
            assert_eq!(
                hit(
                    w - (69.0 * scale) as i32,
                    (16.0 * scale) as i32,
                    w,
                    h,
                    scale,
                    false
                ),
                HTMAXBUTTON
            );
            assert_eq!(
                hit(
                    w - (23.0 * scale) as i32,
                    (16.0 * scale) as i32,
                    w,
                    h,
                    scale,
                    false
                ),
                HTCLIENT
            );
            assert_eq!(hit(1, h / 2, w, h, scale, true), HTCLIENT);
        }
    }
}

#[cfg(test)]
mod hotkey_tests {
    use super::parse_hotkey;

    #[test]
    fn hotkeys_parse_like_the_old_app() {
        assert_eq!(parse_hotkey("Ctrl+Alt+F8"), Ok((0x4000 | 2 | 1, 0x77)));
        assert_eq!(
            parse_hotkey("shift+win+k"),
            Ok((0x4000 | 4 | 8, 'K' as u32))
        );
        assert!(parse_hotkey("F8").is_err());
        assert!(parse_hotkey("Ctrl+Space").is_err());
    }
}

/// Put an image on the clipboard as a device-independent bitmap (what Paint, Discord and Office paste).
pub(crate) fn copy_image(width: u32, height: u32, rgba: &[u8]) -> Result<(), String> {
    use windows::Win32::Foundation::HANDLE;
    use windows::Win32::Graphics::Gdi::{BI_RGB, BITMAPINFOHEADER};
    use windows::Win32::System::DataExchange::{
        CloseClipboard, EmptyClipboard, OpenClipboard, SetClipboardData,
    };
    use windows::Win32::System::Memory::{GMEM_MOVEABLE, GlobalAlloc, GlobalLock, GlobalUnlock};
    use windows::Win32::System::Ole::CF_DIB;
    let header = BITMAPINFOHEADER {
        biSize: size_of::<BITMAPINFOHEADER>() as u32,
        biWidth: width as i32,
        biHeight: -(height as i32), // top-down rows
        biPlanes: 1,
        biBitCount: 32,
        biCompression: BI_RGB.0,
        ..Default::default()
    };
    let pixels = (width * height * 4) as usize;
    // SAFETY: the global block is sized for the header plus pixels and written before the clipboard owns it.
    unsafe {
        let memory = GlobalAlloc(GMEM_MOVEABLE, size_of::<BITMAPINFOHEADER>() + pixels)
            .map_err(|e| e.to_string())?;
        let target = GlobalLock(memory) as *mut u8;
        if target.is_null() {
            return Err("Could not prepare the clipboard image".into());
        }
        std::ptr::copy_nonoverlapping(
            &header as *const _ as *const u8,
            target,
            size_of::<BITMAPINFOHEADER>(),
        );
        let out = std::slice::from_raw_parts_mut(target.add(size_of::<BITMAPINFOHEADER>()), pixels);
        for (dst, src) in out.chunks_exact_mut(4).zip(rgba.chunks_exact(4)) {
            dst.copy_from_slice(&[src[2], src[1], src[0], 255]);
        }
        let _ = GlobalUnlock(memory);
        OpenClipboard(Some(HWND(MAIN.with(|m| m.get()) as *mut c_void)))
            .map_err(|e| e.to_string())?;
        let _ = EmptyClipboard();
        let result = SetClipboardData(CF_DIB.0 as u32, Some(HANDLE(memory.0)))
            .map(|_| ())
            .map_err(|e| e.to_string());
        let _ = CloseClipboard();
        result
    }
}
