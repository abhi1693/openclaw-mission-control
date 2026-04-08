import { nextId } from "./reset";

export interface UserEntity {
  id: string;
  clerk_user_id: string;
  email: string;
  name: string;
  preferred_name: string;
  timezone: string;
  is_super_admin?: boolean;
}

export function buildUser(overrides?: Partial<UserEntity>): UserEntity {
  const id = overrides?.id ?? nextId("user");
  return {
    id,
    clerk_user_id: "local-auth-user",
    email: "local-auth-user@example.com",
    name: "Local User",
    preferred_name: "Local User",
    timezone: "UTC",
    ...overrides,
  };
}
