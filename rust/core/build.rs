use std::env;
use std::fs;
use std::path::{Path, PathBuf};

const START: &str = "HTML = r'''";
const END: &str = "'''.replace(\"__TAGGING_DOCS_URL__\"";

fn main() {
    let manifest = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let source = env::var_os("PLAI_CONTROL_CENTER_SOURCE").map_or_else(
        || manifest.join("../../src/core/prompt_ui.py"),
        PathBuf::from,
    );
    println!("cargo:rerun-if-changed={}", source.display());
    println!("cargo:rerun-if-env-changed=PLAI_CONTROL_CENTER_SOURCE");

    let text = fs::read_to_string(&source).unwrap_or_else(|error| {
        panic!(
            "cannot read Control Center source {}: {error}",
            source.display()
        )
    });
    let start = text.find(START).unwrap_or_else(|| {
        panic!(
            "Control Center HTML start marker missing in {}",
            source.display()
        )
    }) + START.len();
    let tail = &text[start..];
    let end = tail.find(END).unwrap_or_else(|| {
        panic!(
            "Control Center HTML end marker missing in {}",
            source.display()
        )
    });
    let html = &tail[..end];
    if !html.contains("paperless-local-ai Control Center")
        || !html.contains("__TAGGING_DOCS_URL__")
        || !html.contains("__PAPERLESS_SETUP_DOCS_URL__")
        || !html.contains("__APP_VERSION__")
    {
        panic!("Control Center HTML contract changed; refusing to build an incomplete asset");
    }

    let out_dir = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR"));
    write(&out_dir.join("control-center.html"), html.as_bytes());
}

fn write(path: &Path, content: &[u8]) {
    fs::write(path, content)
        .unwrap_or_else(|error| panic!("cannot write {}: {error}", path.display()));
}
