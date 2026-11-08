use std::{fs, path::Path};

/// A literal length like `12px` (not `0px`), or a hex colour like `#a1b2c3`.
fn literal_length(value: &str) -> bool {
    value.starts_with(|c: char| c.is_ascii_digit()) && value != "0px"
}

fn hex_colour(source: &str) -> bool {
    source.match_indices('#').any(|(i, _)| {
        let digits: String = source[i + 1..]
            .chars()
            .take_while(char::is_ascii_alphanumeric)
            .collect();
        matches!(digits.len(), 3 | 4 | 6 | 8) && digits.chars().all(|c| c.is_ascii_hexdigit())
    })
}

#[test]
fn ui_colors_radii_and_spacing_stay_in_tokens() {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("ui");
    for entry in fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.file_name().unwrap() == "tokens.slint"
            || path.extension().is_none_or(|e| e != "slint")
        {
            continue;
        }
        let text = fs::read_to_string(&path).unwrap();
        // Shared controls only: no raw std-widgets form controls (they would look like default widgets).
        if let Some(import) = text.lines().find(|l| l.contains("std-widgets.slint")) {
            for raw in [
                "Button",
                "CheckBox",
                "ComboBox",
                "LineEdit",
                "Slider",
                "SpinBox",
                "DatePicker",
                "Switch",
            ] {
                assert!(
                    !import
                        .split(|c: char| !c.is_ascii_alphanumeric())
                        .any(|w| w == raw),
                    "{}: use the shared {raw} from controls.slint",
                    path.display()
                );
            }
        }
        for (line, source) in text.lines().enumerate() {
            let at = format!("{}:{}", path.display(), line + 1);
            assert!(
                !hex_colour(source) && !source.contains("rgb(") && !source.contains("rgba("),
                "{at} hardcoded colour outside tokens"
            );
            if let Some((_, value)) = source.split_once("radius:") {
                assert!(
                    !literal_length(value.trim()),
                    "{at} radius must use a shape token"
                );
            }
            for property in [
                "spacing",
                "padding",
                "padding-left",
                "padding-right",
                "padding-top",
                "padding-bottom",
            ] {
                if let Some((_, value)) = source.split_once(&format!(" {property}:")) {
                    assert!(
                        !literal_length(value.split(';').next().unwrap().trim()),
                        "{at} spacing must use a token"
                    );
                }
            }
        }
    }
}

#[test]
fn the_guard_catches_each_kind_of_problem() {
    assert!(hex_colour("background: #c42b1c;") && !hex_colour("placeholder: \"#rrggbb\";"));
    assert!(literal_length("12px;") && !literal_length("0px") && !literal_length("Tokens.r-sm;"));
}
