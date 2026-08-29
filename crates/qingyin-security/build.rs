//! Fail closed when security test fixtures enter a non-debug Cargo profile.

use std::env;

const FORBIDDEN_CFG: &str = "qingyin_security_test_support_forbidden";

fn main() {
    println!("cargo::rustc-check-cfg=cfg({FORBIDDEN_CFG})");
    println!("cargo::rerun-if-env-changed=CARGO_FEATURE_TEST_SUPPORT");
    println!("cargo::rerun-if-env-changed=PROFILE");

    let test_support_enabled = env::var_os("CARGO_FEATURE_TEST_SUPPORT").is_some();
    let is_debug_profile = env::var("PROFILE").is_ok_and(|profile| profile == "debug");
    if test_support_enabled && !is_debug_profile {
        println!("cargo::rustc-cfg={FORBIDDEN_CFG}");
    }
}
