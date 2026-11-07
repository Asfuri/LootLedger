use std::{fs, path::Path};

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
        for (line, source) in fs::read_to_string(&path).unwrap().lines().enumerate() {
            assert!(
                !source.contains('#') && !source.contains("rgb(") && !source.contains("rgba("),
                "{}:{} hardcoded color outside tokens",
                path.display(),
                line + 1
            );
            if let Some((_, value)) = source.split_once("radius:") {
                assert!(
                    value.trim_start().starts_with("Tokens."),
                    "{}:{} radius must use a shape token",
                    path.display(),
                    line + 1
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
                if let Some((_, value)) = source.split_once(&format!("{property}:")) {
                    let value = value.split(';').next().unwrap().trim();
                    assert!(
                        value.starts_with("Tokens.") || value == "0px",
                        "{}:{} spacing must use a token",
                        path.display(),
                        line + 1
                    );
                }
            }
            if path.file_name().unwrap() != "controls.slint" {
                let raw_form = source
                    .split(|c: char| !c.is_ascii_alphanumeric() && c != '_')
                    .any(|word| {
                        [
                            "Button",
                            "CheckBox",
                            "ComboBox",
                            "LineEdit",
                            "Slider",
                            "SpinBox",
                            "DatePicker",
                        ]
                        .contains(&word)
                    });
                assert!(
                    !raw_form,
                    "{}:{} use shared controls rather than a raw form widget",
                    path.display(),
                    line + 1
                );
            }
        }
    }
}
