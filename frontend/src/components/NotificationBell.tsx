import { Bell, CheckCheck, LoaderCircle } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useToast, useWorkspace } from '@/components/providers';
import { notificationsApi, type NotificationItem } from '@/lib/notifications-api';
import './notification-bell.css';

function relativeTime(value: string): string {
  const created = new Date(value).getTime();
  if (!Number.isFinite(created)) return '';
  const seconds = Math.max(0, Math.floor((Date.now() - created) / 1000));
  if (seconds < 60) return 'Just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(value).toLocaleDateString();
}

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const { activeWorkspace } = useWorkspace();
  const { pushToast } = useToast();
  const navigate = useNavigate();

  const refreshCount = useCallback(async () => {
    if (!activeWorkspace?.id) {
      setUnreadCount(0);
      return;
    }
    try {
      const count = await notificationsApi.unreadCount();
      setUnreadCount(count);
    } catch {
      // The top bar should remain usable during an API outage. The full error is
      // surfaced when the user explicitly opens the inbox.
    }
  }, [activeWorkspace?.id]);

  const loadItems = useCallback(async () => {
    if (!activeWorkspace?.id) {
      setItems([]);
      setUnreadCount(0);
      return;
    }
    setLoading(true);
    try {
      const [values, count] = await Promise.all([
        notificationsApi.list(30),
        notificationsApi.unreadCount(),
      ]);
      setItems(values);
      setUnreadCount(count);
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Notifications could not be loaded', 'error');
    } finally {
      setLoading(false);
    }
  }, [activeWorkspace?.id, pushToast]);

  useEffect(() => {
    void refreshCount();
    const timer = window.setInterval(() => { void refreshCount(); }, 60_000);
    return () => window.clearInterval(timer);
  }, [refreshCount]);

  const markRead = async (item: NotificationItem) => {
    if (item.readAt) return item;
    const updated = await notificationsApi.markRead(item.id);
    setItems((current) => current.map((value) => (value.id === item.id ? updated : value)));
    setUnreadCount((current) => Math.max(0, current - 1));
    return updated;
  };

  const activate = async (item: NotificationItem) => {
    try {
      await markRead(item);
      setOpen(false);
      // Only navigate to an application-relative path; reject protocol-relative
      // URLs and backslashes that browsers can interpret as external hosts.
      if (item.actionUrl && /^\/(?!\/)[^\\\u0000-\u001f\u007f]*$/.test(item.actionUrl)) navigate(item.actionUrl);
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Notification could not be updated', 'error');
    }
  };

  const markAllRead = async () => {
    if (unreadCount === 0) return;
    try {
      await notificationsApi.markAllRead();
      const now = new Date().toISOString();
      setItems((current) => current.map((item) => (item.readAt ? item : { ...item, readAt: now })));
      setUnreadCount(0);
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Notifications could not be updated', 'error');
    }
  };

  return <div className="notification-center">
    <button
      className="icon-button notification-center__trigger"
      type="button"
      aria-label={unreadCount ? `Notifications, ${unreadCount} unread` : 'Notifications'}
      aria-expanded={open}
      aria-haspopup="dialog"
      onClick={() => { if (!open) void loadItems(); setOpen((value) => !value); }}
    >
      <Bell />
      {unreadCount > 0 ? <span className="notification-center__badge">{unreadCount > 99 ? '99+' : unreadCount}</span> : null}
    </button>
    {open ? <section className="notification-center__popover" role="dialog" aria-label="Notifications">
      <header className="notification-center__header">
        <div><strong>Notifications</strong><small>{unreadCount ? `${unreadCount} unread` : 'You’re all caught up'}</small></div>
        <button type="button" className="notification-center__read-all" onClick={() => void markAllRead()} disabled={unreadCount === 0}>
          <CheckCheck />Mark all read
        </button>
      </header>
      <div className="notification-center__list">
        {loading ? <div className="notification-center__state"><LoaderCircle className="notification-center__spinner" />Loading notifications…</div> : null}
        {!loading && items.length === 0 ? <div className="notification-center__state">No notifications in this workspace yet.</div> : null}
        {!loading ? items.map((item) => <button
          type="button"
          key={item.id}
          className={`notification-center__item ${item.readAt ? '' : 'is-unread'}`}
          onClick={() => void activate(item)}
        >
          <span className={`notification-center__severity notification-center__severity--${item.severity}`} aria-hidden="true" />
          <span className="notification-center__copy">
            <span><strong>{item.title}</strong><time dateTime={item.createdAt}>{relativeTime(item.createdAt)}</time></span>
            <small>{item.body}</small>
            {item.actionLabel ? <em>{item.actionLabel}</em> : null}
          </span>
        </button>) : null}
      </div>
    </section> : null}
  </div>;
}
