import Foundation

public let computerUseServerInstructions = """
Computer Use tools let you interact with macOS apps by performing UI actions.

Some apps might have a separate dedicated plugin or skill. You may want to use that plugin or skill instead of Computer Use when it seems like a good fit for the task. While the separate plugin or skill may not expose every feature in the app, if the plugin can perform the task with its available features, prefer it. If the needed capability is not exposed there, use Computer Use may be appropriate for the missing interaction.

Begin by calling `get_app_state` every turn you want to use Computer Use to get the latest state before acting. Codex will automatically stop the session after each assistant turn, so this step is required before interacting with apps in a new assistant turn.

The available tools are list_apps, get_app_state, click, perform_secondary_action, scroll, drag, set_input_target, type_text, press_key, and set_value. If any of these are not available in your environment, use tool_search to surface one before calling any Computer Use action tools.

Computer Use tools allow you to use the user's apps in the background, so while you're using an app, the user can continue to use other apps on their computer. Avoid doing anything that would disrupt the user's active session, such as overwriting the contents of their clipboard, unless they asked you to!

After each action, use the action result or fetch the latest state to verify the UI changed as expected.
Every action requires the observation_id printed in the latest state for that app. An action consumes its observation even if it fails. Use the new ID from its result, or call get_app_state again; do not queue multiple actions against an old ID.
Coordinates are pixels in the returned screenshot. Clicks never select unrelated descendants or activate windows as a fallback. Window activation, when needed and authorized, must be an explicit exposed secondary action.
CU maintains its own input target and UTF-16 selection per application window, independent of the human system focus. Use set_input_target to bind an observed editable control and optionally an explicit selection; set_value also binds its target and places the CU insertion point at the verified value end. type_text without element_index uses only this bound target, never the system or app focus. Accessibility mode selects a supported direct value or selection write before delivery; keyboard mode requires a verified app-local receiver and never activates the app. Binding is not a guarantee of background keyboard support. After external text changes, keys, or unconfirmed input, observe and explicitly rebind the selection. Prefer semantic button actions to Enter when background keys are unsupported. Never automatically replay an unconfirmed write; text readback does not prove application-level effects.
Prefer element-targeted interactions over coordinate clicks when an index for the targeted element is available. Note that element indices are the sequential integers from the app state's accessibility tree.
Avoid falling back to AppleScript during a computer use session. Prefer Computer Use tools as much as possible to complete tasks.
Ask the user before taking destructive or externally visible actions such as sending, deleting, or purchasing. If helpful, you can ask follow-up questions before taking action to make sure you’re understanding the user’s request correctly.
"""
