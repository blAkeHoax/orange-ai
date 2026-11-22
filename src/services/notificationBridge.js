// src/services/notificationBridge.js - Native Windows Toast Notifications Bridge for Orange AI Desktop 2.0
import { isPermissionGranted, requestPermission, sendNotification } from '@tauri-apps/plugin-notification';
import { getUnacknowledgedEvents, acknowledgeEvent, getSettings } from './tauriBridge';

let isListening = false;
let pollInterval = null;

export async function ensureNotificationPermission() {
  try {
    let granted = await isPermissionGranted();
    if (!granted) {
      const permission = await requestPermission();
      granted = permission === 'granted';
    }
    return granted;
  } catch (err) {
    console.warn('[NotificationBridge] Permission check failed:', err);
    return false;
  }
}

export function formatEventToast(evt) {
  const eventType = evt?.event_type || '';
  const payload = evt?.payload || {};

  if (eventType === 'morning_briefing_ready' || eventType === 'briefing.ready' || eventType === 'briefing_ready') {
    return {
      title: '🌅 Morning Briefing Ready',
      body: payload.content ? `${payload.content.slice(0, 120)}...` : `Daily briefing for ${payload.local_date || 'today'} is available.`
    };
  }

  if (eventType === 'reminder_due' || eventType === 'reminder.due') {
    return {
      title: '⏰ Reminder Due',
      body: payload.message || 'A scheduled reminder is due.'
    };
  }

  if (eventType === 'job_needs_approval' || eventType === 'job.approval') {
    return {
      title: '⚠️ Job Requires Approval',
      body: payload.summary || `Job '${payload.goal || 'Task'}' requires your authorization.`
    };
  }

  if (eventType === 'watcher_alert' || eventType === 'alert') {
    return {
      title: '🔔 System Advisory Alert',
      body: payload.title || payload.message || 'System watcher detected an alert.'
    };
  }

  return null;
}

export async function processUnacknowledgedEvents() {
  try {
    const settings = await getSettings();
    const toastsEnabled = settings?.desktop_toasts_enabled !== false;
    if (!toastsEnabled) {
      return;
    }

    const unacked = await getUnacknowledgedEvents(25);
    if (!Array.isArray(unacked) || unacked.length === 0) {
      return;
    }

    const hasPermission = await ensureNotificationPermission();

    for (const evt of unacked) {
      const toastData = formatEventToast(evt);
      if (toastData && hasPermission && !evt?.payload?.suppress_toast) {
        try {
          sendNotification({
            title: toastData.title,
            body: toastData.body,
          });
        } catch (toastErr) {
          console.warn('[NotificationBridge] Failed to send toast:', toastErr);
        }
      }

      // Acknowledge so it never fires twice
      if (evt.event_id) {
        try {
          await acknowledgeEvent(evt.event_id, evt.event_type);
        } catch (ackErr) {
          console.warn('[NotificationBridge] Failed to acknowledge event:', ackErr);
        }
      }
    }
  } catch (err) {
    console.warn('[NotificationBridge] Error processing unacked events:', err);
  }
}

export function startNotificationBridge(intervalMs = 15000) {
  if (isListening) return () => {};
  isListening = true;

  // Initial check
  processUnacknowledgedEvents();

  // Periodic polling
  pollInterval = setInterval(processUnacknowledgedEvents, intervalMs);

  return () => {
    isListening = false;
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  };
}
