import { Icon, type IconName } from "./Icon";

type NoticeProps = {
  icon?: IconName;
  title: string;
  body?: string;
  tone?: "plain" | "alert";
  onDismiss?: () => void;
  dismissLabel?: string;
};

export function Notice({ icon = "info", title, body, tone = "plain", onDismiss, dismissLabel = "Dismiss" }: NoticeProps) {
  return (
    <div className={`notice${tone === "alert" ? " notice-alert" : ""}`} role={tone === "alert" ? "alert" : "note"}>
      <Icon name={icon} size={26} strokeWidth={2.5} />
      <div className="notice-body">
        <p className="notice-title">{title}</p>
        {body && <p className="muted">{body}</p>}
      </div>
      {onDismiss && (
        <button type="button" className="notice-dismiss" onClick={onDismiss}>
          {dismissLabel}
        </button>
      )}
    </div>
  );
}
