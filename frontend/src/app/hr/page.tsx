"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import {
  useCreateHeadcountRequestHrHeadcountPost,
  useCreateEmploymentActionHrActionsPost,
  useListHeadcountRequestsHrHeadcountGet,
  useListEmploymentActionsHrActionsGet,
  useListAgentOnboardingHrOnboardingGet,
  useCreateAgentOnboardingHrOnboardingPost,
  useUpdateAgentOnboardingHrOnboardingOnboardingIdPatch,
} from "@/api/generated/hr/hr";
import { useListDepartmentsDepartmentsGet, useListEmployeesEmployeesGet } from "@/api/generated/org/org";

export default function HRPage() {
  const departments = useListDepartmentsDepartmentsGet();
  const departmentList = departments.data ?? [];
  const employees = useListEmployeesEmployeesGet();
  const employeeList = employees.data ?? [];

  const headcount = useListHeadcountRequestsHrHeadcountGet();
  const actions = useListEmploymentActionsHrActionsGet();
  const onboarding = useListAgentOnboardingHrOnboardingGet();
  const headcountList = headcount.data ?? [];
  const actionList = actions.data ?? [];
  const onboardingList = onboarding.data ?? [];

  const [hcDeptId, setHcDeptId] = useState<string>("");
  const [hcManagerId, setHcManagerId] = useState<string>("");
  const [hcRole, setHcRole] = useState("");
  const [hcType, setHcType] = useState<"human" | "agent">("human");
  const [hcQty, setHcQty] = useState("1");
  const [hcJust, setHcJust] = useState("");

  const [actEmployeeId, setActEmployeeId] = useState<string>("");
  const [actIssuerId, setActIssuerId] = useState<string>("");
  const [actType, setActType] = useState("praise");
  const [actNotes, setActNotes] = useState("");


  const [onboardAgentName, setOnboardAgentName] = useState("");
  const [onboardRole, setOnboardRole] = useState("");
  const [onboardPrompt, setOnboardPrompt] = useState("");
  const [onboardCronMs, setOnboardCronMs] = useState("");
  const [onboardTools, setOnboardTools] = useState("");
  const [onboardOwnerId, setOnboardOwnerId] = useState<string>("");
  const [onboardNotes, setOnboardNotes] = useState("");
  const createHeadcount = useCreateHeadcountRequestHrHeadcountPost({
    mutation: {
      onSuccess: () => {
        setHcRole("");
        setHcJust("");
        setHcQty("1");
        headcount.refetch();
      },
    },
  });

  const createAction = useCreateEmploymentActionHrActionsPost({
    mutation: {
      onSuccess: () => {
        setActNotes("");
        actions.refetch();
      },
    },
  });

  const createOnboarding = useCreateAgentOnboardingHrOnboardingPost({
    mutation: {
      onSuccess: () => {
        setOnboardAgentName("");
        setOnboardRole("");
        setOnboardPrompt("");
        setOnboardCronMs("");
        setOnboardTools("");
        setOnboardOwnerId("");
        setOnboardNotes("");
        onboarding.refetch();
      },
    },
  });

  const updateOnboarding = useUpdateAgentOnboardingHrOnboardingOnboardingIdPatch({
    mutation: {
      onSuccess: () => onboarding.refetch(),
    },
  });

  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">HR</h1>
          <p className="mt-1 text-sm text-muted-foreground">Headcount requests and employment actions.</p>
        </div>
        <Button variant="outline" onClick={() => { headcount.refetch(); actions.refetch(); }}>
          Refresh
        </Button>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Headcount request</CardTitle>
            <CardDescription>Managers request; HR fulfills later.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Select value={hcDeptId} onChange={(e) => setHcDeptId(e.target.value)}>
              <option value="">Select department</option>
              {departmentList.map((d) => (
                <option key={d.id ?? d.name} value={d.id ?? ""}>{d.name}</option>
              ))}
            </Select>
            <Select value={hcManagerId} onChange={(e) => setHcManagerId(e.target.value)}>
              <option value="">Requesting manager</option>
              {employeeList.map((e) => (
                <option key={e.id ?? e.name} value={e.id ?? ""}>{e.name}</option>
              ))}
            </Select>
            <Input placeholder="Role title" value={hcRole} onChange={(e) => setHcRole(e.target.value)} />
            <div className="grid grid-cols-2 gap-2">
              <Select value={hcType} onChange={(e) => setHcType(e.target.value === "agent" ? "agent" : "human")}>
                <option value="human">human</option>
                <option value="agent">agent</option>
              </Select>
              <Input placeholder="Quantity" value={hcQty} onChange={(e) => setHcQty(e.target.value)} />
            </div>
            <Textarea placeholder="Justification (optional)" value={hcJust} onChange={(e) => setHcJust(e.target.value)} />
            <Button
              onClick={() =>
                createHeadcount.mutate({
                  data: {
                    department_id: Number(hcDeptId),
                    requested_by_manager_id: Number(hcManagerId),
                    role_title: hcRole,
                    employee_type: hcType,
                    quantity: Number(hcQty || "1"),
                    justification: hcJust.trim() ? hcJust : null,
                  },
                })
              }
              disabled={!hcDeptId || !hcManagerId || !hcRole.trim() || createHeadcount.isPending}
            >
              Submit
            </Button>
            {createHeadcount.error ? (
              <div className="text-sm text-destructive">{(createHeadcount.error as Error).message}</div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Employment action</CardTitle>
            <CardDescription>Log HR actions (praise/warning/pip/termination).</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Select value={actEmployeeId} onChange={(e) => setActEmployeeId(e.target.value)}>
              <option value="">Employee</option>
              {employeeList.map((e) => (
                <option key={e.id ?? e.name} value={e.id ?? ""}>{e.name}</option>
              ))}
            </Select>
            <Select value={actIssuerId} onChange={(e) => setActIssuerId(e.target.value)}>
              <option value="">Issued by</option>
              {employeeList.map((e) => (
                <option key={e.id ?? e.name} value={e.id ?? ""}>{e.name}</option>
              ))}
            </Select>
            <Select value={actType} onChange={(e) => setActType(e.target.value)}>
              <option value="praise">praise</option>
              <option value="warning">warning</option>
              <option value="pip">pip</option>
              <option value="termination">termination</option>
            </Select>
            <Textarea placeholder="Notes (optional)" value={actNotes} onChange={(e) => setActNotes(e.target.value)} />
            <Button
              onClick={() =>
                createAction.mutate({
                  data: {
                    employee_id: Number(actEmployeeId),
                    issued_by_employee_id: Number(actIssuerId),
                    action_type: actType,
                    notes: actNotes.trim() ? actNotes : null,
                  },
                })
              }
              disabled={!actEmployeeId || !actIssuerId || createAction.isPending}
            >
              Create
            </Button>
            {createAction.error ? (
              <div className="text-sm text-destructive">{(createAction.error as Error).message}</div>
            ) : null}
          </CardContent>
        </Card>

        <Card className="sm:col-span-2">
          <CardHeader>
            <CardTitle>Recent HR activity</CardTitle>
            <CardDescription>Latest headcount + actions</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div>
              <div className="mb-2 text-sm font-medium">Headcount requests</div>
              <ul className="space-y-2">
                {headcountList.slice(0, 10).map((r) => (
                  <li key={String(r.id)} className="rounded-md border p-3 text-sm">
                    <div className="font-medium">{r.role_title} × {r.quantity} ({r.employee_type})</div>
                    <div className="text-xs text-muted-foreground">dept #{r.department_id} · status: {r.status}</div>
                  </li>
                ))}
                {headcountList.length === 0 ? (
                  <li className="text-sm text-muted-foreground">None yet.</li>
                ) : null}
              </ul>
            </div>
            <div>
              <div className="mb-2 text-sm font-medium">Employment actions</div>
              <ul className="space-y-2">
                {actionList.slice(0, 10).map((a) => (
                  <li key={String(a.id)} className="rounded-md border p-3 text-sm">
                    <div className="font-medium">{a.action_type} → employee #{a.employee_id}</div>
                    <div className="text-xs text-muted-foreground">issued by #{a.issued_by_employee_id}</div>
                  </li>
                ))}
                {actionList.length === 0 ? (
                  <li className="text-sm text-muted-foreground">None yet.</li>
                ) : null}
              </ul>
            </div>
          </CardContent>
        </Card>


      <div className="mt-6 grid gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Agent onboarding</CardTitle>
            <CardDescription>HR logs prompts, cron, tools, and spawn status (Mission Control only).</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-3">
              <Input placeholder="Agent name" value={onboardAgentName} onChange={(e) => setOnboardAgentName(e.target.value)} />
              <Input placeholder="Role/title" value={onboardRole} onChange={(e) => setOnboardRole(e.target.value)} />
              <Textarea placeholder="Prompt / system instructions" value={onboardPrompt} onChange={(e) => setOnboardPrompt(e.target.value)} />
              <Input placeholder="Cron interval ms (e.g. 300000)" value={onboardCronMs} onChange={(e) => setOnboardCronMs(e.target.value)} />
              <Textarea placeholder="Tools/permissions (JSON or text)" value={onboardTools} onChange={(e) => setOnboardTools(e.target.value)} />
              <Select value={onboardOwnerId} onChange={(e) => setOnboardOwnerId(e.target.value)}>
                <option value="">Owner (HR)</option>
                {employeeList.map((e) => (
                  <option key={e.id ?? e.name} value={e.id ?? ""}>{e.name}</option>
                ))}
              </Select>
              <Textarea placeholder="Notes" value={onboardNotes} onChange={(e) => setOnboardNotes(e.target.value)} />
              <Button
                onClick={() =>
                  createOnboarding.mutate({
                    data: {
                      agent_name: onboardAgentName,
                      role_title: onboardRole,
                      prompt: onboardPrompt,
                      cron_interval_ms: onboardCronMs ? Number(onboardCronMs) : null,
                      tools_json: onboardTools.trim() ? onboardTools : null,
                      owner_hr_id: onboardOwnerId ? Number(onboardOwnerId) : null,
                      status: "planned",
                      notes: onboardNotes.trim() ? onboardNotes : null,
                    },
                  })
                }
                disabled={!onboardAgentName.trim() || !onboardRole.trim() || !onboardPrompt.trim() || createOnboarding.isPending}
              >
                Create onboarding
              </Button>
            </div>
            <div>
              <div className="mb-2 text-sm font-medium">Current onboardings</div>
              <ul className="space-y-2">
                {onboardingList.map((o) => (
                  <li key={String(o.id)} className="rounded-md border p-3 text-sm">
                    <div className="font-medium">{o.agent_name} · {o.role_title}</div>
                    <div className="text-xs text-muted-foreground">status: {o.status} · cron: {o.cron_interval_ms ?? "—"}</div>
                    <div className="mt-2 grid gap-2">
                      <Select
                        value={o.status ?? ""}
                        onChange={(e) =>
                          updateOnboarding.mutate({ onboardingId: Number(o.id), data: { status: e.target.value || null } })
                        }
                      >
                        <option value="planned">planned</option>
                        <option value="spawning">spawning</option>
                        <option value="spawned">spawned</option>
                        <option value="verified">verified</option>
                        <option value="blocked">blocked</option>
                      </Select>
                      <Input
                        placeholder="Spawned agent id"
                        defaultValue={o.spawned_agent_id ?? ""}
                        onBlur={(e) =>
                          updateOnboarding.mutate({ onboardingId: Number(o.id), data: { spawned_agent_id: e.currentTarget.value || null } })
                        }
                      />
                      <Input
                        placeholder="Session key"
                        defaultValue={o.session_key ?? ""}
                        onBlur={(e) =>
                          updateOnboarding.mutate({ onboardingId: Number(o.id), data: { session_key: e.currentTarget.value || null } })
                        }
                      />
                      <Textarea
                        placeholder="Notes"
                        defaultValue={o.notes ?? ""}
                        onBlur={(e) =>
                          updateOnboarding.mutate({ onboardingId: Number(o.id), data: { notes: e.currentTarget.value || null } })
                        }
                      />
                    </div>
                  </li>
                ))}
                {onboardingList.length === 0 ? (
                  <li className="text-sm text-muted-foreground">No onboarding records yet.</li>
                ) : null}
              </ul>
            </div>
          </CardContent>
        </Card>
      </div>
      </div>
    </main>
  );
}
