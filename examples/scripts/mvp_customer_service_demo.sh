#!/usr/bin/env bash
set -euo pipefail

agentfactory init

agentfactory create-agent \
  --prompt "创建一个客服 Agent，支持售前、售后、退款、投诉、转人工、订单查询和客服知识库查询" \
  --draft \
  --no-stream

PACKAGE_PATH=".agentfactory/packages/drafts/customer-service-agent"
PATCHED_PATH=".agentfactory/packages/drafts/customer-service-agent-v1.1.0"

agentfactory validate-agent "$PACKAGE_PATH"
agentfactory test-agent "$PACKAGE_PATH"
agentfactory register-agent "$PACKAGE_PATH"
agentfactory release customer-service-agent --version 1.0.0 --channel available
agentfactory run-agent customer-service-agent --version 1.0.0 --input "帮我查一下订单 123"
agentfactory run-agent customer-service-agent --version 1.0.0 --input "我要返厂维修" || true

agentfactory plan-upgrade "$PACKAGE_PATH" \
  --prompt "增加返厂维修意图" \
  --target-version 1.1.0 \
  --output .agentfactory/patch_plan.yaml

agentfactory approve-patch generated-tool-repair-ticket-create \
  --actor user \
  --patch-plan .agentfactory/patch_plan.yaml

agentfactory apply-patch-plan "$PACKAGE_PATH" \
  --output "$PATCHED_PATH" \
  --target-version 1.1.0

agentfactory validate-agent "$PATCHED_PATH"
agentfactory test-agent "$PATCHED_PATH"
agentfactory register-agent "$PATCHED_PATH"
agentfactory release customer-service-agent --version 1.1.0 --channel candidate
