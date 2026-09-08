package main

import (
    "encoding/json"
    "io"
    "os"
)

// Private Combo worker protocol. The upstream service owns all snapshots/actions.
func main() {
    decoder := json.NewDecoder(os.Stdin)
    encoder := json.NewEncoder(os.Stdout)
    sessions := map[string]*service{}
    for {
        var request struct {
            Op string `json:"op"`
            SessionID string `json:"session_id"`
            Name string `json:"name"`
            Arguments map[string]any `json:"arguments"`
        }
        if err := decoder.Decode(&request); err != nil {
            if err != io.EOF { _ = encoder.Encode(map[string]any{"bridge_error":err.Error()}) }
            return
        }
        var response any
        switch request.Op {
        case "tools":
            response = map[string]any{"tools":toolDefinitions(),"instructions":serverInstructions}
        case "start":
            sessions[request.SessionID] = newService()
            response = map[string]any{"ok":true}
        case "stop":
            delete(sessions,request.SessionID)
            response = map[string]any{"ok":true}
        case "permissions":
            response = map[string]any{"required":false,"accessibility":true,"screen_recording":true}
        case "request_permission":
            response = map[string]any{"ok":true}
        case "call":
            svc := sessions[request.SessionID]
            if svc == nil { response = map[string]any{"bridge_error":"inactive session"} } else {
                response = svc.callTool(request.Name,request.Arguments)
            }
        default:
            response = map[string]any{"bridge_error":"unknown bridge operation"}
        }
        if encoder.Encode(response) != nil { return }
    }
}
