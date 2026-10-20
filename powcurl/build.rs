fn main() {
    println!("cargo:rerun-if-changed=native/player.c");

    if std::env::var("CARGO_CFG_TARGET_FAMILY").as_deref() == Ok("windows") {
        cc::Build::new()
            .file("native/player.c")
            .warnings(true)
            .compile("powcurl_player");
        println!("cargo:rustc-link-lib=user32");
    }
}
