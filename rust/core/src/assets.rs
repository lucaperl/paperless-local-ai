const CONTROL_CENTER_TEMPLATE: &str =
    include_str!(concat!(env!("OUT_DIR"), "/control-center.html"));

pub fn render_control_center(app_version: &str) -> String {
    let app_version = app_version.trim();
    let app_version = if app_version.is_empty() {
        "dev"
    } else {
        app_version
    };
    let docs_ref = if matches!(app_version, "dev" | "main") {
        "main".to_owned()
    } else {
        format!("v{}", app_version.strip_prefix('v').unwrap_or(app_version))
    };
    let docs_base = format!("https://github.com/lucaperl/paperless-local-ai/blob/{docs_ref}");
    CONTROL_CENTER_TEMPLATE
        .replace(
            "__TAGGING_DOCS_URL__",
            &format!("{docs_base}/docs/tagging.md"),
        )
        .replace(
            "__PAPERLESS_SETUP_DOCS_URL__",
            &format!("{docs_base}/docs/paperless-setup.md"),
        )
        .replace("__APP_VERSION__", app_version)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn release_docs_link_to_the_matching_tag() {
        let html = render_control_center("0.3.5-rc.1");
        assert!(html.contains("/blob/v0.3.5-rc.1/docs/tagging.md"));
        assert!(html.contains("/blob/v0.3.5-rc.1/docs/paperless-setup.md"));
        assert!(!html.contains("__APP_VERSION__"));
    }

    #[test]
    fn development_docs_link_to_main() {
        let html = render_control_center("dev");
        assert!(html.contains("/blob/main/docs/tagging.md"));
    }
}
