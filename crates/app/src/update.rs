//! Updates from this project's GitHub releases. The only network traffic in LootLedger: ask GitHub for the
//! latest release, download its LootLedger.exe, check it against the SHA-256 GitHub publishes, and stage
//! it next to the running exe. It replaces the exe when the app closes (or on "Restart now").
//! Nothing about the user or their matches is sent.

use serde_json::Value;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

const LATEST: &str = "https://api.github.com/repos/femboypuppy/LootLedger/releases/latest";

#[derive(Debug, Clone)]
pub struct Release {
    pub version: String,
    pub url: String,
    pub sha256: String,
}

/// Version numbers compared as numbers: "v0.10.0" is newer than "0.9.3".
pub fn newer(current: &str, tag: &str) -> bool {
    let parse = |v: &str| -> Vec<u64> {
        v.trim_start_matches('v')
            .split(['.', '-'])
            .map_while(|p| p.parse().ok())
            .collect()
    };
    let (now, then) = (parse(current), parse(tag));
    !then.is_empty() && then > now
}

/// The latest release if it is newer than this build and has a verifiable LootLedger.exe.
pub fn check(current: &str) -> Result<Option<Release>, String> {
    let body = get(LATEST)?;
    let release: Value =
        serde_json::from_slice(&body).map_err(|e| format!("Unexpected answer from GitHub: {e}"))?;
    let tag = release["tag_name"].as_str().unwrap_or_default();
    if !newer(current, tag)
        || release["draft"].as_bool() == Some(true)
        || release["prerelease"].as_bool() == Some(true)
    {
        return Ok(None);
    }
    let asset = release["assets"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|a| a["name"] == "LootLedger.exe");
    let Some(asset) = asset else { return Ok(None) };
    let (Some(url), Some(sha256)) = (
        asset["browser_download_url"].as_str(),
        asset["digest"]
            .as_str()
            .and_then(|d| d.strip_prefix("sha256:")),
    ) else {
        return Ok(None); // no checksum published: never install something we cannot verify
    };
    Ok(Some(Release {
        version: tag.trim_start_matches('v').to_owned(),
        url: url.to_owned(),
        sha256: sha256.to_ascii_lowercase(),
    }))
}

pub fn staged_path(exe: &Path) -> PathBuf {
    exe.with_extension("exe.new")
}

fn old_path(exe: &Path) -> PathBuf {
    exe.with_extension("exe.old")
}

/// Download the release and keep it next to `exe` as LootLedger.exe.new, only if its SHA-256 matches.
pub fn download(release: &Release, exe: &Path) -> Result<PathBuf, String> {
    let data = get(&release.url)?;
    stage(&data, &release.sha256, exe)
}

fn stage(data: &[u8], sha256: &str, exe: &Path) -> Result<PathBuf, String> {
    let actual = Sha256::digest(data)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    if actual != sha256 {
        return Err(
            "The downloaded update did not match its published checksum, so it was not installed."
                .into(),
        );
    }
    let staged = staged_path(exe);
    let temp = exe.with_extension("exe.download");
    std::fs::write(&temp, data)
        .and_then(|_| std::fs::rename(&temp, &staged))
        .map_err(|e| format!("Could not save the update: {e}"))?;
    Ok(staged)
}

/// Swap a staged update in. Windows lets a running exe be renamed, so this works while the app is open.
pub fn apply(exe: &Path) -> std::io::Result<bool> {
    let staged = staged_path(exe);
    if !staged.exists() {
        return Ok(false);
    }
    let old = old_path(exe);
    let _ = std::fs::remove_file(&old);
    std::fs::rename(exe, &old)?;
    if let Err(e) = std::fs::rename(&staged, exe) {
        let _ = std::fs::rename(&old, exe); // put the working version back
        return Err(e);
    }
    Ok(true)
}

/// The previous version is left behind by `apply`; it can be deleted once the new one runs.
pub fn cleanup(exe: &Path) {
    let _ = std::fs::remove_file(old_path(exe));
}

/// HTTPS GET with Windows' own HTTP stack (system proxy and certificates; follows GitHub's redirects).
#[cfg(windows)]
fn get(url: &str) -> Result<Vec<u8>, String> {
    use windows::Win32::Networking::WinHttp::*;
    use windows::core::{HSTRING, PCWSTR};
    let rest = url.strip_prefix("https://").ok_or("Only HTTPS is used")?;
    let (host, path) = rest
        .split_once('/')
        .map_or((rest, "/".to_owned()), |(h, p)| (h, format!("/{p}")));
    struct Handle(*mut core::ffi::c_void);
    impl Drop for Handle {
        fn drop(&mut self) {
            if !self.0.is_null() {
                // SAFETY: a handle returned by WinHttp*, closed once.
                unsafe {
                    let _ = WinHttpCloseHandle(self.0);
                }
            }
        }
    }
    let failed =
        |what: &str| format!("Could not reach GitHub ({what}). Check your internet connection.");
    // SAFETY: plain WinHTTP calls; every handle is closed by `Handle`, buffers outlive each call.
    unsafe {
        let agent = HSTRING::from(format!("LootLedger/{}", env!("CARGO_PKG_VERSION")));
        let session = Handle(WinHttpOpen(
            &agent,
            WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,
            PCWSTR::null(),
            PCWSTR::null(),
            0,
        ));
        if session.0.is_null() {
            return Err(failed("open"));
        }
        let _ = WinHttpSetTimeouts(session.0, 10_000, 10_000, 15_000, 60_000);
        let connection = Handle(WinHttpConnect(
            session.0,
            &HSTRING::from(host),
            INTERNET_DEFAULT_HTTPS_PORT,
            0,
        ));
        if connection.0.is_null() {
            return Err(failed("connect"));
        }
        let request = Handle(WinHttpOpenRequest(
            connection.0,
            &HSTRING::from("GET"),
            &HSTRING::from(path),
            PCWSTR::null(),
            PCWSTR::null(),
            std::ptr::null(),
            WINHTTP_FLAG_SECURE,
        ));
        if request.0.is_null() {
            return Err(failed("request"));
        }
        let headers: Vec<u16> = "Accept: application/vnd.github+json, application/octet-stream\r\n"
            .encode_utf16()
            .collect();
        WinHttpSendRequest(request.0, Some(&headers), None, 0, 0, 0).map_err(|_| failed("send"))?;
        WinHttpReceiveResponse(request.0, std::ptr::null_mut()).map_err(|_| failed("response"))?;
        let mut status = 0u32;
        let mut size = std::mem::size_of::<u32>() as u32;
        WinHttpQueryHeaders(
            request.0,
            WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
            PCWSTR::null(),
            Some(&mut status as *mut u32 as *mut _),
            &mut size,
            std::ptr::null_mut(),
        )
        .map_err(|_| failed("status"))?;
        if status != 200 {
            return Err(format!("GitHub answered {status}; try again later."));
        }
        let mut body = Vec::new();
        let mut chunk = vec![0u8; 64 * 1024];
        loop {
            let mut read = 0u32;
            WinHttpReadData(
                request.0,
                chunk.as_mut_ptr() as *mut _,
                chunk.len() as u32,
                &mut read,
            )
            .map_err(|_| failed("read"))?;
            if read == 0 {
                break;
            }
            body.extend_from_slice(&chunk[..read as usize]);
            if body.len() > 200 * 1024 * 1024 {
                return Err("The update is unexpectedly large, so it was not downloaded.".into());
            }
        }
        Ok(body)
    }
}

#[cfg(not(windows))]
fn get(_: &str) -> Result<Vec<u8>, String> {
    Err("Updates are only available on Windows".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn versions_compare_as_numbers() {
        assert!(newer("0.8.0", "v0.8.1"));
        assert!(newer("0.9.3", "v0.10.0"));
        assert!(!newer("0.8.0", "v0.8.0"));
        assert!(!newer("0.8.1", "v0.8.0"));
        assert!(!newer("0.8.0", "nightly"));
    }

    #[test]
    fn only_a_verified_download_is_staged_and_swapped_in() {
        let dir = std::env::temp_dir().join(format!("lootledger-update-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let exe = dir.join("LootLedger.exe");
        std::fs::write(&exe, b"old").unwrap();
        assert!(stage(b"new", "00", &exe).is_err());
        assert!(!apply(&exe).unwrap());
        let sum = Sha256::digest(b"new")
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>();
        stage(b"new", &sum, &exe).unwrap();
        assert!(apply(&exe).unwrap());
        assert_eq!(std::fs::read(&exe).unwrap(), b"new");
        assert_eq!(std::fs::read(old_path(&exe)).unwrap(), b"old");
        cleanup(&exe);
        assert!(!old_path(&exe).exists());
        std::fs::remove_dir_all(dir).unwrap();
    }

    /// Talks to GitHub: run with `cargo test -p lootledger -- --ignored live_release`.
    #[test]
    #[ignore]
    fn live_release_is_found_and_verifies() {
        let release = check("0.0.1")
            .unwrap()
            .expect("a published release with a checksum");
        let dir = std::env::temp_dir().join(format!("lootledger-live-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let staged = download(&release, &dir.join("LootLedger.exe")).unwrap();
        assert!(std::fs::metadata(&staged).unwrap().len() > 1_000_000);
        std::fs::remove_dir_all(dir).unwrap();
    }
}
