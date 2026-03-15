import { nextId } from "./reset";

export interface OrgEntity {
  id: string;
  name: string;
  is_active: boolean;
  role: string;
}

export function buildOrg(overrides?: Partial<OrgEntity>): OrgEntity {
  const id = overrides?.id ?? nextId("org");
  return {
    id,
    name: `Testing Org ${id}`,
    is_active: true,
    role: "owner",
    ...overrides,
  };
}

export interface OrgMemberEntity {
  id: string;
  organization_id: string;
  user_id: string;
  role: string;
  all_boards_read: boolean;
  all_boards_write: boolean;
  board_access: Array<{ board_id: string; can_read: boolean; can_write: boolean }>;
  created_at?: string;
  updated_at?: string;
}

export function buildOrgMember(overrides?: Partial<OrgMemberEntity>): OrgMemberEntity {
  const id = overrides?.id ?? nextId("membership");
  return {
    id,
    organization_id: "org-1",
    user_id: "user-1",
    role: "owner",
    all_boards_read: true,
    all_boards_write: true,
    board_access: [],
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}
