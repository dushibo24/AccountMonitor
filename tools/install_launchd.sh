#!/bin/zsh
set -eu

project_dir=${0:A:h:h}
python_path=$(command -v python3)
launch_agents_dir="$HOME/Library/LaunchAgents"
plist_path="$launch_agents_dir/com.dushibo.codex-daily-report.plist"
service_name="gui/$(id -u)/com.dushibo.codex-daily-report"

if [[ ! -f "$project_dir/config.json" || ! -f "$project_dir/auth.json" ]]; then
  print -u2 "缺少 config.json 或 auth.json，请先完成配置和手动推送测试。"
  exit 1
fi

xml_escape() {
  print -rn -- "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' \
    -e 's/"/\&quot;/g' -e "s/'/\&apos;/g"
}

escaped_python=$(xml_escape "$python_path")
escaped_script=$(xml_escape "$project_dir/codex_daily_report.py")
escaped_project=$(xml_escape "$project_dir")
escaped_log=$(xml_escape "$project_dir/report.log")

mkdir -p "$launch_agents_dir"
umask 077
cat > "$plist_path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.dushibo.codex-daily-report</string>
  <key>ProgramArguments</key>
  <array>
    <string>$escaped_python</string>
    <string>$escaped_script</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$escaped_project</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>14</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$escaped_log</string>
  <key>StandardErrorPath</key>
  <string>$escaped_log</string>
</dict>
</plist>
EOF

plutil -lint "$plist_path"
launchctl bootout "$service_name" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$plist_path"
print "已安装并加载：$plist_path"
print "每天 14:00 运行；可执行以下命令立即测试："
print "launchctl kickstart $service_name"
