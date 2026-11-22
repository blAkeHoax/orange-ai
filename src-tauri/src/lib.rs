pub mod commands;
pub mod job_object;
pub mod python_runtime;
pub mod single_instance;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager,
};

pub fn run() {
    // 1. Enforce single-instance mutex
    let _instance_guard = match single_instance::SingleInstanceGuard::acquire(
        "Local\\OrangeAIDesktopSingleInstanceMutex",
    ) {
        Ok(guard) => guard,
        Err(e) => {
            eprintln!("[single-instance] {}", e);
            std::process::exit(0);
        }
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(commands::MinimizeToTrayState(AtomicBool::new(true)))
        .setup(|app| {
            let handle = app.handle().clone();

            // Build Tray Menu items
            let open_item = MenuItem::with_id(app, "open", "Open Orange AI", true, None::<&str>)?;
            let briefing_item = MenuItem::with_id(
                app,
                "briefing",
                "Generate Morning Briefing",
                true,
                None::<&str>,
            )?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit Orange AI", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&open_item, &briefing_item, &quit_item])?;

            let mut tray_builder = TrayIconBuilder::new()
                .menu(&tray_menu)
                .tooltip("Orange AI — Autonomous Assistant")
                .show_menu_on_left_click(false);

            if let Some(icon) = app.default_window_icon() {
                tray_builder = tray_builder.icon(icon.clone());
            }

            tray_builder
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.unminimize();
                            let _ = window.set_focus();
                        }
                    }
                    "briefing" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.unminimize();
                            let _ = window.set_focus();
                            let _ = window.emit("tray://trigger-briefing", ());
                        }
                    }
                    "quit" => {
                        let app_handle = app.clone();
                        tauri::async_runtime::spawn(async move {
                            if let Some(supervisor) = app_handle
                                .try_state::<Arc<python_runtime::RuntimeSupervisor>>()
                            {
                                if let Ok(runtime) = supervisor.get_runtime().await {
                                    let _ = runtime
                                        .call("system.shutdown", serde_json::json!({}))
                                        .await;
                                }
                            }
                            app_handle.exit(0);
                        });
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.unminimize();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            // Spawn and supervise Python runtime without panicking on failure
            let supervisor = python_runtime::RuntimeSupervisor::new(handle);
            let supervisor_init = supervisor.clone();

            tauri::async_runtime::block_on(async move {
                let status = supervisor_init.initialize().await;
                eprintln!("[runtime-supervisor] Startup status: {:?}", status);
            });

            app.manage(supervisor);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let app = window.app_handle();
                if let Some(min_state) = app.try_state::<commands::MinimizeToTrayState>() {
                    if min_state.0.load(Ordering::SeqCst) {
                        api.prevent_close();
                        let _ = window.hide();
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_handshake_status,
            commands::retry_handshake,
            commands::open_data_folder,
            commands::open_official_releases,
            commands::ping,
            commands::get_health,
            commands::get_memory,
            commands::get_jobs,
            commands::send_message,
            commands::confirm_action,
            commands::call_runtime,
            commands::shutdown,
            commands::prepare_for_update,
            commands::minimize_window,
            commands::toggle_maximize_window,
            commands::close_window,
            commands::set_window_size,
            commands::set_theme,
            commands::toggle_drawer,
            commands::select_view,
            commands::set_minimize_to_tray
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
