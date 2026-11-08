fn main() {
    let config = slint_build::CompilerConfiguration::new().with_style("material".into());
    slint_build::compile_with_config("ui/app.slint", config).expect("compile Slint UI");
    // Icon, version information and the manifest (per-monitor v2 DPI, long paths, common controls 6).
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        println!("cargo:rerun-if-changed=assets/lootledger.rc");
        println!("cargo:rerun-if-changed=assets/lootledger.manifest");
        println!("cargo:rerun-if-changed=assets/lootledger.ico");
        embed_resource::compile("assets/lootledger.rc", embed_resource::NONE)
            .manifest_required()
            .expect("embed Windows resources");
    }
}
