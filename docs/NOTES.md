


    Based on what I've seen in the investigation, here are the risks:

    Low risk (heartbeats are simple tasks):                                                                                                                                                                                   
    - Heartbeats just read HEARTBEAT.md, check board status, and report back — this is well within a 27B model's capability
    - The current fallback to qwen2.5:7b was already handling heartbeats (poorly, but running)                                                                                                                                
    - qwen3.5:27b is significantly stronger than the 7b that's been running

    Actual risks to watch:

    1. Instruction following quality — The agents' system prompts and HEARTBEAT.md contain specific instructions. A weaker model might misinterpret them, produce malformed responses, or hallucinate actions. The 27B should
    handle this well though.
    2. Token context window — Your agents have contextTokens: 128000 configured, but qwen3.5:27b likely has a 32K-128K context window. The current sessions are running at ~32K input tokens each. Should fit, but worth
    confirming.
    3. Concurrent load on the Mac Studio — 9+ sessions hitting Ollama every 60 seconds. The M1 Ultra with 128GB can handle it, but if multiple sessions queue up simultaneously, heartbeat cycles could take longer than 60s
    and pile up.
    4. The real risk is zero — Right now 100% of runs are failing anyway (gpt-5.4 rate limited, qwen2.5:7b too weak). A better local model is strictly an improvement over the current state.

    Bottom line: Very low risk. The heartbeat task is simple, qwen3.5:27b is more than capable, and the current situation (everything failing) is worse than any realistic downside.



      2. When reassignment is impossible, fall back to the waiting reason. Rafael said "atribuir ao Miguel" but Miguel
   isn't on the board. Instead of asking to register Miguel, use the name in the waiting reason: "Aguardando
  assinatura do Miguel."

    1. qwen3.5:27b is timing out (status 408, "LLM request timed out") — this is because the model has thinking mode enabled by default, generating 1000+ tokens before responding. The gateway has a request timeout and
  qwen3.5:27b exceeds it.
  2. After timeout, it falls back to gpt-5.4 → rate limited → falls back to qwen2.5:32b → and at 22:43 one succeeded.

● They're the same files — stored in tests/ but the manifest expects them in add/. So the real missing files that need to be populated:                                                             
                                                                                                                                                                                                    
  ┌───────────────────────┬───────────────────────────────────────────────────────────┬────────────────────────┐                                                                                    
  │         Skill         │                      What's missing                       │ Source exists in repo? │                                                                               
  ├───────────────────────┼───────────────────────────────────────────────────────────┼────────────────────────┤                                                                                    
  │ add-image-vision      │ 4 files in add/plugins/image-vision/                      │ Yes                    │                                                                                  
  ├───────────────────────┼───────────────────────────────────────────────────────────┼────────────────────────┤                                                                                    
  │ add-embeddings        │ modify/ directory (3 files)                               │ Yes                    │                                                                                    
  ├───────────────────────┼───────────────────────────────────────────────────────────┼────────────────────────┤                                                                                    
  │ add-long-term-context │ 3 test files in add/ (they're in tests/ instead)          │ Yes                    │                                                                                    
  ├───────────────────────┼───────────────────────────────────────────────────────────┼────────────────────────┤                                                                                    
  │ add-taskflow          │ 2 files in modify/ (container-runtime.ts, group-queue.ts) │ Yes                    │                                                                                    
  └───────────────────────┴───────────────────────────────────────────────────────────┴────────────────────────┘                                                                                    
                                                                                                                                                                                                    
  The long-term-context one is debatable — the tests are already in the skill, just under tests/ not add/. The others are genuinely missing. Want me to fix the real gaps (image-vision, embeddings,
   taskflow), or also reorganize the long-term-context tests?