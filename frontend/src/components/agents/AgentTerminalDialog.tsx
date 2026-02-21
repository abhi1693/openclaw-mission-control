"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";

import { type AgentRead } from "@/api/generated/model";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface AgentTerminalDialogProps {
  agent: AgentRead | null;
  onClose: () => void;
}

type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

export function AgentTerminalDialog({
  agent,
  onClose,
}: AgentTerminalDialogProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const terminalInstanceRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const statusRef = useRef<ConnectionStatus>("disconnected");
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [error, setError] = useState<string | null>(null);

  const updateStatus = useCallback((newStatus: ConnectionStatus) => {
    statusRef.current = newStatus;
    setStatus(newStatus);
  }, []);

  const sendInput = useCallback((data: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "input", content: data }));
    }
  }, []);

  const sendResize = useCallback((cols: number, rows: number) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "resize", cols, rows }));
    }
  }, []);

  // Connection management via useEffect
  useEffect(() => {
    if (!agent || !terminalRef.current) return;

    // Initialize terminal
    const terminal = new Terminal({
      cursorBlink: true,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      fontSize: 14,
      theme: {
        background: "#1e1e2e",
        foreground: "#cdd6f4",
        cursor: "#f5e0dc",
        cursorAccent: "#1e1e2e",
        selectionBackground: "#45475a",
        black: "#45475a",
        red: "#f38ba8",
        green: "#a6e3a1",
        yellow: "#f9e2af",
        blue: "#89b4fa",
        magenta: "#f5c2e7",
        cyan: "#94e2d5",
        white: "#bac2de",
        brightBlack: "#585b70",
        brightRed: "#f38ba8",
        brightGreen: "#a6e3a1",
        brightYellow: "#f9e2af",
        brightBlue: "#89b4fa",
        brightMagenta: "#f5c2e7",
        brightCyan: "#94e2d5",
        brightWhite: "#a6adc8",
      },
    });

    const fitAddon = new FitAddon();
    const webLinksAddon = new WebLinksAddon();

    terminal.loadAddon(fitAddon);
    terminal.loadAddon(webLinksAddon);

    terminal.open(terminalRef.current);
    fitAddon.fit();

    terminalInstanceRef.current = terminal;
    fitAddonRef.current = fitAddon;

    terminal.onData(sendInput);

    terminal.writeln("Welcome to OpenClaw Agent Terminal");
    terminal.writeln(`Agent: ${agent.name} (${agent.id})`);
    terminal.writeln("Connecting...\r\n");

    // Establish WebSocket connection - status starts as "connecting" from default state
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Intentional: WebSocket setup requires sync state update
    updateStatus("connecting");

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/api/v1/agents/${agent.id}/terminal`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      updateStatus("connected");
      terminalInstanceRef.current?.writeln(
        "\x1b[32mConnected to agent session.\x1b[0m\r\n",
      );
      terminalInstanceRef.current?.focus();
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "output") {
        terminalInstanceRef.current?.write(data.content);
      } else if (data.type === "error") {
        setError(data.message);
        updateStatus("error");
      }
    };

    ws.onerror = () => {
      setError("WebSocket connection error");
      updateStatus("error");
    };

    ws.onclose = (event) => {
      if (statusRef.current !== "error") {
        updateStatus("disconnected");
        if (event.code !== 1000) {
          terminalInstanceRef.current?.writeln(
            `\r\n\x1b[33mConnection closed (code: ${event.code}).\x1b[0m`,
          );
        }
      }
    };

    const handleResize = () => {
      if (fitAddonRef.current && terminalInstanceRef.current) {
        fitAddonRef.current.fit();
        sendResize(
          terminalInstanceRef.current.cols,
          terminalInstanceRef.current.rows,
        );
      }
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      if (wsRef.current) {
        wsRef.current.close(1000);
        wsRef.current = null;
      }
      terminal.dispose();
      terminalInstanceRef.current = null;
      fitAddonRef.current = null;
      updateStatus("disconnected");
    };
  }, [agent, sendInput, sendResize, updateStatus]);

  const handleClose = () => {
    if (wsRef.current) {
      wsRef.current.close(1000);
      wsRef.current = null;
    }
    onClose();
  };

  const handleReconnect = () => {
    if (!agent) return;

    terminalInstanceRef.current?.clear();
    terminalInstanceRef.current?.writeln("Reconnecting...\r\n");

    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close(1000);
      wsRef.current = null;
    }

    updateStatus("connecting");
    setError(null);

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/api/v1/agents/${agent.id}/terminal`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      updateStatus("connected");
      terminalInstanceRef.current?.writeln(
        "\x1b[32mConnected to agent session.\x1b[0m\r\n",
      );
      terminalInstanceRef.current?.focus();
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "output") {
        terminalInstanceRef.current?.write(data.content);
      } else if (data.type === "error") {
        setError(data.message);
        updateStatus("error");
      }
    };

    ws.onerror = () => {
      setError("WebSocket connection error");
      updateStatus("error");
    };

    ws.onclose = (event) => {
      if (statusRef.current !== "error") {
        updateStatus("disconnected");
        if (event.code !== 1000) {
          terminalInstanceRef.current?.writeln(
            `\r\n\x1b[33mConnection closed (code: ${event.code}).\x1b[0m`,
          );
        }
      }
    };
  };

  const statusBadge = {
    disconnected: (
      <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-800">
        Disconnected
      </span>
    ),
    connecting: (
      <span className="inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800">
        Connecting...
      </span>
    ),
    connected: (
      <span className="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-800">
        Connected
      </span>
    ),
    error: (
      <span className="inline-flex items-center rounded-full bg-rose-100 px-2.5 py-0.5 text-xs font-medium text-rose-800">
        Error
      </span>
    ),
  };

  return (
    <Dialog open={!!agent} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent
        className="max-w-4xl"
        aria-label={`Terminal session for ${agent?.name ?? "agent"}`}
      >
        <DialogHeader>
          <div className="flex items-center justify-between">
            <DialogTitle>Agent Terminal</DialogTitle>
            {statusBadge[status]}
          </div>
          <DialogDescription>
            Interactive terminal session with {agent?.name ?? "agent"}
          </DialogDescription>
        </DialogHeader>

        <div
          ref={terminalRef}
          className="h-[400px] w-full overflow-hidden rounded-lg border border-slate-700 bg-[#1e1e2e]"
          style={{ padding: "8px" }}
        />

        {error ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
            {error}
          </div>
        ) : null}

        <DialogFooter>
          {(status === "disconnected" || status === "error") && (
            <Button variant="outline" onClick={handleReconnect}>
              Reconnect
            </Button>
          )}
          <Button variant="outline" onClick={handleClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
