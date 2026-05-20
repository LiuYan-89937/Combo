#!/bin/bash
# 随机城市列表
cities=("Beijing" "Shanghai" "Tokyo" "London" "New+York" "Paris" "Sydney" "Dubai" "Singapore" "Berlin" "Moscow" "Seoul" "Bangkok" "San+Francisco" "Los+Angeles")
# 随机选一个
idx=$((RANDOM % ${#cities[@]}))
city="${cities[$idx]}"
# 获取天气
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
curl -s "wttr.in/${city}?format=%l:+%c+%t+%h+%w" 2>/dev/null || echo "查询失败"
echo ""
