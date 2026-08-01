import { Copy } from "./Copy";
import { Icon } from "./Icon";
import { formatDay } from "../format";

export type DisplaySettings = {
  largeText: boolean;
  highContrast: boolean;
  simplified: boolean;
};

type DisplayBarProps = {
  activeClock?: string;
  timeZone: string;
  ready?: boolean;
  settings: DisplaySettings;
  onToggle: (key: keyof DisplaySettings) => void;
};

export function DisplayBar({ activeClock, timeZone, ready, settings, onToggle }: DisplayBarProps) {
  return (
    <div className="band">
      <div className="shell displaybar">
        <div className="displaybar-date">
          {activeClock && <span className="today-date">{formatDay(activeClock, timeZone)}</span>}
          {ready !== undefined && (
            <span className={`status-tag ${ready ? "status-tag-verified" : "status-tag-review"}`} role="status">
              <Icon name={ready ? "check" : "alert"} size={16} strokeWidth={3} />
              {ready ? (
                <Copy plain="Plan verified" simple="Plan checked" />
              ) : (
                <Copy plain="Plan needs review" simple="Plan not checked yet" />
              )}
            </span>
          )}
        </div>

        <div className="display-options">
          <span className="kicker" id="display-options-label">
            <Copy plain="Display" simple="How it looks" />
          </span>
          <div className="toggle-row" role="group" aria-labelledby="display-options-label">
          <DisplayToggle
            pressed={settings.largeText}
            onClick={() => onToggle("largeText")}
            plain="Bigger text"
            simple="Bigger text"
          />
          <DisplayToggle
            pressed={settings.highContrast}
            onClick={() => onToggle("highContrast")}
            plain="Higher contrast"
            simple="Stronger colours"
          />
          <DisplayToggle
            pressed={settings.simplified}
            onClick={() => onToggle("simplified")}
            plain="Simpler words"
            simple="Simpler words"
          />
          </div>
        </div>
      </div>
    </div>
  );
}

function DisplayToggle({
  pressed,
  onClick,
  plain,
  simple,
}: {
  pressed: boolean;
  onClick: () => void;
  plain: string;
  simple: string;
}) {
  return (
    <button type="button" className="toggle" aria-pressed={pressed} onClick={onClick}>
      {pressed && <Icon name="check" size={15} strokeWidth={3.5} />}
      <Copy plain={plain} simple={simple} />
    </button>
  );
}
