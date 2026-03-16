"use client";

export const dynamic = "force-dynamic";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { useAuth } from "@/auth/clerk";
import { useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/mutator";
import {
  type listGatewaysApiV1GatewaysGetResponse,
  useListGatewaysApiV1GatewaysGet,
} from "@/api/generated/gateways/gateways";
import type { MarketplaceSkillCardRead } from "@/api/generated/model";
import {
  listMarketplaceSkillsApiV1SkillsMarketplaceGet,
  type listMarketplaceSkillsApiV1SkillsMarketplaceGetResponse,
  useInstallMarketplaceSkillApiV1SkillsMarketplaceSkillIdInstallPost,
  useListMarketplaceSkillsApiV1SkillsMarketplaceGet,
  useUninstallMarketplaceSkillApiV1SkillsMarketplaceSkillIdUninstallPost,
} from "@/api/generated/skills-marketplace/skills-marketplace";
import {
  type listSkillPacksApiV1SkillsPacksGetResponse,
  useListSkillPacksApiV1SkillsPacksGet,
} from "@/api/generated/skills/skills";
import { SkillInstallDialog } from "@/components/skills/SkillInstallDialog";
import { MarketplaceSkillsTable } from "@/components/skills/MarketplaceSkillsTable";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { Button, buttonVariants } from "@/components/ui/button";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { useUrlSorting } from "@/lib/use-url-sorting";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const MARKETPLACE_SKILLS_SORTABLE_COLUMNS = [
  "name",
  "category",
  "risk",
  "source",
  "updated_at",
];
const MARKETPLACE_DEFAULT_PAGE_SIZE = 25;
const MARKETPLACE_PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;

type MarketplaceSkillListParams = {
  gateway_id: string;
  search?: string;
  category?: string;
  risk?: string;
  pack_id?: string;
  limit?: number;
  offset?: number;
};

const RISK_SORT_ORDER: Record<string, number> = {
  safe: 10,
  low: 20,
  minimal: 30,
  medium: 40,
  moderate: 50,
  elevated: 60,
  high: 70,
  critical: 80,
  none: 90,
  unknown: 100,
};

function formatRiskLabel(risk: string) {
  const normalized = risk.trim().toLowerCase();
  if (!normalized) {
    return "Unknown";
  }

  switch (normalized) {
    case "safe":
      return "Safe";
    case "low":
      return "Low";
    case "minimal":
      return "Minimal";
    case "medium":
      return "Medium";
    case "moderate":
      return "Moderate";
    case "elevated":
      return "Elevated";
    case "high":
      return "High";
    case "critical":
      return "Critical";
    case "none":
      return "None";
    case "unknown":
      return "Unknown";
    default:
      return normalized
        .split(/[\s_-]+/)
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
  }
}

function formatCategoryLabel(category: string) {
  const normalized = category.trim();
  if (!normalized) {
    return "Uncategorized";
  }
  return normalized
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function parsePositiveIntParam(value: string | null, fallback: number) {
  if (!value) {
    return fallback;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return fallback;
  }
  return parsed;
}

function parsePageSizeParam(value: string | null) {
  const parsed = parsePositiveIntParam(value, MARKETPLACE_DEFAULT_PAGE_SIZE);
  if (
    MARKETPLACE_PAGE_SIZE_OPTIONS.includes(
      parsed as (typeof MARKETPLACE_PAGE_SIZE_OPTIONS)[number],
    )
  ) {
    return parsed;
  }
  return MARKETPLACE_DEFAULT_PAGE_SIZE;
}

/**
 * Skills Marketplace admin page.
 *
 * Data-flow notes:
 * - URL query params are treated as the shareable source-of-truth for filters
 *   and pagination (we mirror local state -> URL via `router.replace`).
 * - We keep a *separate* query (without pagination) for building filter option
 *   lists (categories/risks) so options don't disappear just because the current
 *   page is filtered/paginated.
 * - Total row count is best-effort: when the API provides `x-total-count`, we
 *   use it; otherwise we infer whether there is a next page from page-size.
 */
export default function SkillsMarketplacePage() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const [selectedSkill, setSelectedSkill] =
    useState<MarketplaceSkillCardRead | null>(null);
  const [gatewayInstalledById, setGatewayInstalledById] = useState<
    Record<string, boolean>
  >({});
  const [installedGatewayNamesBySkillId, setInstalledGatewayNamesBySkillId] =
    useState<Record<string, { id: string; name: string }[]>>({});
  const [isGatewayStatusLoading, setIsGatewayStatusLoading] = useState(false);
  const [gatewayStatusError, setGatewayStatusError] = useState<string | null>(
    null,
  );
  const [installingGatewayId, setInstallingGatewayId] = useState<string | null>(
    null,
  );
  const initialSearch = searchParams.get("search") ?? "";
  const initialCategory = (searchParams.get("category") ?? "all")
    .trim()
    .toLowerCase();
  const initialRisk = (searchParams.get("risk") ?? "safe").trim().toLowerCase();
  const initialPage = parsePositiveIntParam(searchParams.get("page"), 1);
  const initialPageSize = parsePageSizeParam(searchParams.get("limit"));
  const [searchTerm, setSearchTerm] = useState(initialSearch);
  const [selectedCategory, setSelectedCategory] = useState<string>(
    initialCategory || "all",
  );
  const [selectedRisk, setSelectedRisk] = useState<string>(
    initialRisk || "safe",
  );
  const [currentPage, setCurrentPage] = useState(initialPage);
  const [pageSize, setPageSize] = useState(initialPageSize);

  const { sorting, onSortingChange } = useUrlSorting({
    allowedColumnIds: MARKETPLACE_SKILLS_SORTABLE_COLUMNS,
    defaultSorting: [{ id: "name", desc: false }],
    paramPrefix: "skills_marketplace",
  });

  const gatewaysQuery = useListGatewaysApiV1GatewaysGet<
    listGatewaysApiV1GatewaysGetResponse,
    ApiError
  >(undefined, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchOnMount: "always",
      refetchInterval: 30_000,
    },
  });

  const gateways = useMemo(
    () =>
      gatewaysQuery.data?.status === 200
        ? (gatewaysQuery.data.data.items ?? [])
        : [],
    [gatewaysQuery.data],
  );

  const resolvedGatewayId = gateways[0]?.id ?? "";
  const normalizedCategory = useMemo(() => {
    const value = selectedCategory.trim().toLowerCase();
    return value.length > 0 ? value : "all";
  }, [selectedCategory]);
  const normalizedRisk = useMemo(() => {
    const value = selectedRisk.trim().toLowerCase();
    return value.length > 0 ? value : "safe";
  }, [selectedRisk]);
  const normalizedSearch = useMemo(() => searchTerm.trim(), [searchTerm]);
  const selectedPackId = searchParams.get("packId");
  const skillsParams = useMemo<MarketplaceSkillListParams>(() => {
    const params: MarketplaceSkillListParams = {
      gateway_id: resolvedGatewayId,
      limit: pageSize,
      offset: (currentPage - 1) * pageSize,
    };
    if (normalizedSearch) {
      params.search = normalizedSearch;
    }
    if (normalizedCategory !== "all") {
      params.category = normalizedCategory;
    }
    if (normalizedRisk && normalizedRisk !== "all") {
      params.risk = normalizedRisk;
    }
    if (selectedPackId) {
      params.pack_id = selectedPackId;
    }
    return params;
  }, [
    currentPage,
    pageSize,
    normalizedCategory,
    normalizedRisk,
    normalizedSearch,
    resolvedGatewayId,
    selectedPackId,
  ]);
  // Fetch a non-paginated (or minimally constrained) slice for building filter options.
  // Keeping this separate avoids "missing" categories/risks when the main list is paginated.
  const filterOptionsParams = useMemo<MarketplaceSkillListParams>(() => {
    const params: MarketplaceSkillListParams = {
      gateway_id: resolvedGatewayId,
    };
    if (normalizedSearch) {
      params.search = normalizedSearch;
    }
    if (selectedPackId) {
      params.pack_id = selectedPackId;
    }
    return params;
  }, [normalizedSearch, resolvedGatewayId, selectedPackId]);

  const skillsQuery = useListMarketplaceSkillsApiV1SkillsMarketplaceGet<
    listMarketplaceSkillsApiV1SkillsMarketplaceGetResponse,
    ApiError
  >(skillsParams, {
    query: {
      enabled: Boolean(isSignedIn && isAdmin && resolvedGatewayId),
      refetchOnMount: "always",
      refetchInterval: 15_000,
    },
  });

  const skills = useMemo<MarketplaceSkillCardRead[]>(
    () => (skillsQuery.data?.status === 200 ? skillsQuery.data.data : []),
    [skillsQuery.data],
  );
  const filterOptionSkillsQuery =
    useListMarketplaceSkillsApiV1SkillsMarketplaceGet<
      listMarketplaceSkillsApiV1SkillsMarketplaceGetResponse,
      ApiError
    >(filterOptionsParams, {
      query: {
        enabled: Boolean(isSignedIn && isAdmin && resolvedGatewayId),
        refetchOnMount: "always",
        refetchInterval: 15_000,
      },
    });
  const filterOptionSkills = useMemo<MarketplaceSkillCardRead[]>(
    () =>
      filterOptionSkillsQuery.data?.status === 200
        ? filterOptionSkillsQuery.data.data
        : [],
    [filterOptionSkillsQuery.data],
  );

  const packsQuery = useListSkillPacksApiV1SkillsPacksGet<
    listSkillPacksApiV1SkillsPacksGetResponse,
    ApiError
  >({
    query: {
      enabled: Boolean(isSignedIn && isAdmin),
      refetchOnMount: "always",
    },
  });

  const packs = useMemo(
    () => (packsQuery.data?.status === 200 ? packsQuery.data.data : []),
    [packsQuery.data],
  );
  const selectedPack = useMemo(
    () => packs.find((pack) => pack.id === selectedPackId) ?? null,
    [packs, selectedPackId],
  );

  const filteredSkills = useMemo(() => skills, [skills]);
  // Prefer the API total-count header when available (true pagination).
  // When missing, we fall back to a heuristic for "has next page".
  const totalCountInfo = useMemo(() => {
    if (skillsQuery.data?.status !== 200) {
      return { hasKnownTotal: false, total: skills.length };
    }
    const totalCountHeader = skillsQuery.data.headers.get("x-total-count");
    if (
      typeof totalCountHeader === "string" &&
      totalCountHeader.trim() !== ""
    ) {
      const parsed = Number(totalCountHeader);
      if (Number.isFinite(parsed) && parsed >= 0) {
        return { hasKnownTotal: true, total: parsed };
      }
    }
    return { hasKnownTotal: false, total: skills.length };
  }, [skills, skillsQuery.data]);
  const totalSkills = useMemo(() => {
    if (totalCountInfo.hasKnownTotal) {
      return totalCountInfo.total;
    }
    return (currentPage - 1) * pageSize + skills.length;
  }, [currentPage, pageSize, skills.length, totalCountInfo]);
  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(totalSkills / pageSize)),
    [pageSize, totalSkills],
  );
  const hasNextPage = useMemo(() => {
    if (totalCountInfo.hasKnownTotal) {
      return currentPage < totalPages;
    }
    return skills.length === pageSize;
  }, [
    currentPage,
    pageSize,
    skills.length,
    totalCountInfo.hasKnownTotal,
    totalPages,
  ]);
  const rangeStart = totalSkills === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const rangeEnd =
    totalSkills === 0 ? 0 : (currentPage - 1) * pageSize + skills.length;

  const categoryFilterOptions = useMemo(() => {
    const byValue = new Map<string, string>();
    for (const skill of filterOptionSkills) {
      const raw = (skill.category || "Uncategorized").trim();
      const label = raw.length > 0 ? raw : "Uncategorized";
      const value = label.trim().toLowerCase();
      if (!value || value === "all" || byValue.has(value)) {
        continue;
      }
      byValue.set(value, label);
    }
    if (normalizedCategory !== "all" && !byValue.has(normalizedCategory)) {
      byValue.set(normalizedCategory, formatCategoryLabel(normalizedCategory));
    }
    return Array.from(byValue.entries())
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [filterOptionSkills, normalizedCategory]);

  const riskFilterOptions = useMemo(() => {
    const set = new Set<string>();
    for (const skill of filterOptionSkills) {
      const risk = (skill.risk || "unknown").trim().toLowerCase();
      const normalized = risk.length > 0 ? risk : "unknown";
      if (normalized !== "all") {
        set.add(normalized);
      }
    }
    if (normalizedRisk !== "all") {
      set.add(normalizedRisk);
    }
    const risks = Array.from(set);
    return risks.sort((a, b) => {
      const rankA = RISK_SORT_ORDER[a] ?? 1000;
      const rankB = RISK_SORT_ORDER[b] ?? 1000;
      if (rankA !== rankB) {
        return rankA - rankB;
      }
      return a.localeCompare(b);
    });
  }, [filterOptionSkills, normalizedRisk]);

  useEffect(() => {
    if (
      selectedCategory !== "all" &&
      !categoryFilterOptions.some(
        (category) => category.value === selectedCategory.trim().toLowerCase(),
      )
    ) {
      setSelectedCategory("all");
    }
  }, [categoryFilterOptions, selectedCategory]);

  useEffect(() => {
    if (
      selectedRisk !== "all" &&
      !riskFilterOptions.includes(selectedRisk.trim().toLowerCase())
    ) {
      setSelectedRisk("safe");
    }
  }, [riskFilterOptions, selectedRisk]);

  useEffect(() => {
    setCurrentPage(1);
  }, [
    normalizedCategory,
    normalizedRisk,
    normalizedSearch,
    pageSize,
    resolvedGatewayId,
    selectedPackId,
  ]);

  useEffect(() => {
    if (totalCountInfo.hasKnownTotal && currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalCountInfo.hasKnownTotal, totalPages]);

  // Mirror local filter/page state back into the URL so the view is shareable and
  // back/forward navigation works. We use `replace` (not push) to avoid filling
  // browser history with every keystroke / filter tweak.
  useEffect(() => {
    const nextParams = new URLSearchParams(searchParams.toString());
    const normalizedSearchForUrl = searchTerm.trim();
    if (normalizedSearchForUrl) {
      nextParams.set("search", normalizedSearchForUrl);
    } else {
      nextParams.delete("search");
    }

    if (selectedCategory !== "all") {
      nextParams.set("category", selectedCategory);
    } else {
      nextParams.delete("category");
    }

    if (selectedRisk !== "safe") {
      nextParams.set("risk", selectedRisk);
    } else {
      nextParams.delete("risk");
    }

    if (pageSize !== MARKETPLACE_DEFAULT_PAGE_SIZE) {
      nextParams.set("limit", String(pageSize));
    } else {
      nextParams.delete("limit");
    }

    if (currentPage > 1) {
      nextParams.set("page", String(currentPage));
    } else {
      nextParams.delete("page");
    }

    const currentQuery = searchParams.toString();
    const nextQuery = nextParams.toString();
    if (nextQuery !== currentQuery) {
      router.replace(nextQuery ? `${pathname}?${nextQuery}` : pathname, {
        scroll: false,
      });
    }
  }, [
    currentPage,
    pathname,
    pageSize,
    router,
    searchParams,
    searchTerm,
    selectedCategory,
    selectedRisk,
  ]);

  const loadSkillsByGateway = useCallback(async () => {
    // NOTE: This is technically N+1 (one request per gateway). We intentionally
    // parallelize requests to keep the UI responsive and avoid slow sequential
    // fetches. If this becomes a bottleneck for large gateway counts, add a
    // backend batch endpoint to return installation state across all gateways.
    const gatewaySkills = await Promise.all(
      gateways.map(async (gateway) => {
        const response = await listMarketplaceSkillsApiV1SkillsMarketplaceGet({
          gateway_id: gateway.id,
        });
        return {
          gatewayId: gateway.id,
          gatewayName: gateway.name,
          skills: response.status === 200 ? response.data : [],
        };
      }),
    );

    return gatewaySkills;
  }, [gateways]);

  const updateInstalledGatewayNames = useCallback(
    ({
      skillId,
      gatewayId,
      gatewayName,
      installed,
    }: {
      skillId: string;
      gatewayId: string;
      gatewayName: string;
      installed: boolean;
    }) => {
      setInstalledGatewayNamesBySkillId((previous) => {
        const installedOn = previous[skillId] ?? [];
        if (installed) {
          if (installedOn.some((gateway) => gateway.id === gatewayId)) {
            return previous;
          }
          return {
            ...previous,
            [skillId]: [...installedOn, { id: gatewayId, name: gatewayName }],
          };
        }
        return {
          ...previous,
          [skillId]: installedOn.filter((gateway) => gateway.id !== gatewayId),
        };
      });
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;

    const loadInstalledGatewaysBySkill = async () => {
      if (
        !isSignedIn ||
        !isAdmin ||
        gateways.length === 0 ||
        skills.length === 0
      ) {
        setInstalledGatewayNamesBySkillId({});
        return;
      }

      try {
        const gatewaySkills = await Promise.all(
          gateways.map(async (gateway) => {
            const response =
              await listMarketplaceSkillsApiV1SkillsMarketplaceGet({
                gateway_id: gateway.id,
              });
            return {
              gatewayId: gateway.id,
              gatewayName: gateway.name,
              skills: response.status === 200 ? response.data : [],
            };
          }),
        );

        if (cancelled) return;

        const nextInstalledGatewayNamesBySkillId: Record<
          string,
          { id: string; name: string }[]
        > = {};
        for (const skill of skills) {
          nextInstalledGatewayNamesBySkillId[skill.id] = [];
        }

        for (const {
          gatewayId,
          gatewayName,
          skills: gatewaySkillRows,
        } of gatewaySkills) {
          for (const skill of gatewaySkillRows) {
            if (!skill.installed) continue;
            if (!nextInstalledGatewayNamesBySkillId[skill.id]) continue;
            nextInstalledGatewayNamesBySkillId[skill.id].push({
              id: gatewayId,
              name: gatewayName,
            });
          }
        }

        setInstalledGatewayNamesBySkillId(nextInstalledGatewayNamesBySkillId);
      } catch {
        if (cancelled) return;
        setInstalledGatewayNamesBySkillId({});
      }
    };

    void loadInstalledGatewaysBySkill();

    return () => {
      cancelled = true;
    };
  }, [gateways, isAdmin, isSignedIn, skills]);

  const installMutation =
    useInstallMarketplaceSkillApiV1SkillsMarketplaceSkillIdInstallPost<ApiError>(
      {
        mutation: {
          onSuccess: async (_, variables) => {
            await queryClient.invalidateQueries({
              queryKey: ["/api/v1/skills/marketplace"],
            });
            setGatewayInstalledById((previous) => ({
              ...previous,
              [variables.params.gateway_id]: true,
            }));
            const gatewayName = gateways.find(
              (gateway) => gateway.id === variables.params.gateway_id,
            )?.name;
            if (gatewayName) {
              updateInstalledGatewayNames({
                skillId: variables.skillId,
                gatewayId: variables.params.gateway_id,
                gatewayName,
                installed: true,
              });
            }
          },
        },
      },
      queryClient,
    );

  const uninstallMutation =
    useUninstallMarketplaceSkillApiV1SkillsMarketplaceSkillIdUninstallPost<ApiError>(
      {
        mutation: {
          onSuccess: async (_, variables) => {
            await queryClient.invalidateQueries({
              queryKey: ["/api/v1/skills/marketplace"],
            });
            setGatewayInstalledById((previous) => ({
              ...previous,
              [variables.params.gateway_id]: false,
            }));
            const gatewayName = gateways.find(
              (gateway) => gateway.id === variables.params.gateway_id,
            )?.name;
            if (gatewayName) {
              updateInstalledGatewayNames({
                skillId: variables.skillId,
                gatewayId: variables.params.gateway_id,
                gatewayName,
                installed: false,
              });
            }
          },
        },
      },
      queryClient,
    );

  useEffect(() => {
    let cancelled = false;

    const loadGatewayStatus = async () => {
      if (!selectedSkill) {
        setGatewayInstalledById({});
        setGatewayStatusError(null);
        setIsGatewayStatusLoading(false);
        return;
      }

      if (gateways.length === 0) {
        setGatewayInstalledById({});
        setGatewayStatusError(null);
        setIsGatewayStatusLoading(false);
        return;
      }

      setIsGatewayStatusLoading(true);
      setGatewayStatusError(null);
      try {
        const gatewaySkills = await loadSkillsByGateway();
        const entries = gatewaySkills.map(
          ({ gatewayId, skills: gatewaySkillRows }) => {
            const row = gatewaySkillRows.find(
              (skill) => skill.id === selectedSkill.id,
            );
            return [gatewayId, Boolean(row?.installed)] as const;
          },
        );
        if (cancelled) return;
        setGatewayInstalledById(Object.fromEntries(entries));
      } catch (error) {
        if (cancelled) return;
        setGatewayStatusError(
          error instanceof Error
            ? error.message
            : "Unable to load gateway status.",
        );
      } finally {
        if (!cancelled) {
          setIsGatewayStatusLoading(false);
        }
      }
    };

    void loadGatewayStatus();

    return () => {
      cancelled = true;
    };
  }, [gateways, loadSkillsByGateway, selectedSkill]);

  const mutationError =
    installMutation.error?.message ?? uninstallMutation.error?.message ?? null;

  const isMutating = installMutation.isPending || uninstallMutation.isPending;

  const handleGatewayInstallAction = async (
    gatewayId: string,
    isInstalled: boolean,
  ) => {
    if (!selectedSkill) return;
    setInstallingGatewayId(gatewayId);
    try {
      if (isInstalled) {
        await uninstallMutation.mutateAsync({
          skillId: selectedSkill.id,
          params: { gateway_id: gatewayId },
        });
      } else {
        await installMutation.mutateAsync({
          skillId: selectedSkill.id,
          params: { gateway_id: gatewayId },
        });
      }
    } finally {
      setInstallingGatewayId(null);
    }
  };

  return (
    <>
      <DashboardPageLayout
        signedOut={{
          message: "Sign in to manage marketplace skills.",
          forceRedirectUrl: "/skills/marketplace",
        }}
        title="Skills Marketplace"
        description={
          selectedPack
            ? `${totalSkills} skill${
                totalSkills === 1 ? "" : "s"
              } for ${selectedPack.name}.`
            : `${totalSkills} skill${
                totalSkills === 1 ? "" : "s"
              } synced from packs.`
        }
        isAdmin={isAdmin}
        adminOnlyMessage="Only organization owners and admins can manage skills."
        stickyHeader
      >
        <div className="space-y-6">
          {gateways.length === 0 ? (
            <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600 shadow-sm">
              <p className="font-medium text-slate-900">
                No gateways available yet.
              </p>
              <p className="mt-2">
                Create a gateway first, then return here to manage installs.
              </p>
              <Link
                href="/gateways/new"
                className={`${buttonVariants({ variant: "primary", size: "md" })} mt-4`}
              >
                Create gateway
              </Link>
            </div>
          ) : (
            <>
              <div className="mb-5 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="grid gap-4 md:grid-cols-[1fr_240px_240px]">
                  <div>
                    <label
                      htmlFor="marketplace-search"
                      className="mb-1 block text-sm font-medium text-slate-700"
                    >
                      Search
                    </label>
                    <Input
                      id="marketplace-search"
                      value={searchTerm}
                      onChange={(event) => setSearchTerm(event.target.value)}
                      placeholder="Search by name, description, category, pack, source..."
                      type="search"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="marketplace-category-filter"
                      className="mb-1 block text-sm font-medium text-slate-700"
                    >
                      Category
                    </label>
                    <Select
                      value={selectedCategory}
                      onValueChange={setSelectedCategory}
                    >
                      <SelectTrigger
                        id="marketplace-category-filter"
                        className="h-11"
                      >
                        <SelectValue placeholder="All categories" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All categories</SelectItem>
                        {categoryFilterOptions.map((category) => (
                          <SelectItem
                            key={category.value}
                            value={category.value}
                          >
                            {category.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <label
                      htmlFor="marketplace-risk-filter"
                      className="mb-1 block text-sm font-medium text-slate-700"
                    >
                      Risk
                    </label>
                    <Select
                      value={selectedRisk}
                      onValueChange={setSelectedRisk}
                    >
                      <SelectTrigger
                        id="marketplace-risk-filter"
                        className="h-11"
                      >
                        <SelectValue placeholder="Safe" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All risks</SelectItem>
                        {riskFilterOptions.map((risk) => (
                          <SelectItem key={risk} value={risk}>
                            {formatRiskLabel(risk)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>
              <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
                <MarketplaceSkillsTable
                  skills={filteredSkills}
                  installedGatewayNamesBySkillId={
                    installedGatewayNamesBySkillId
                  }
                  isLoading={skillsQuery.isLoading}
                  sorting={sorting}
                  onSortingChange={onSortingChange}
                  stickyHeader
                  isMutating={isMutating}
                  onSkillClick={setSelectedSkill}
                  emptyState={{
                    title: "No marketplace skills yet",
                    description:
                      "Add packs first, then synced skills will appear here.",
                    actionHref: "/skills/packs/new",
                    actionLabel: "Add your first pack",
                  }}
                />
              </div>
              <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 shadow-sm">
                <div className="flex items-center gap-3">
                  <p>
                    Showing {rangeStart}-{rangeEnd} of {totalSkills}
                  </p>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                      Rows
                    </span>
                    <Select
                      value={String(pageSize)}
                      onValueChange={(value) => {
                        const next = Number.parseInt(value, 10);
                        if (
                          MARKETPLACE_PAGE_SIZE_OPTIONS.includes(
                            next as (typeof MARKETPLACE_PAGE_SIZE_OPTIONS)[number],
                          )
                        ) {
                          setPageSize(next);
                        }
                      }}
                    >
                      <SelectTrigger
                        id="marketplace-footer-limit-filter"
                        className="h-8 w-24"
                      >
                        <SelectValue placeholder="25" />
                      </SelectTrigger>
                      <SelectContent>
                        {MARKETPLACE_PAGE_SIZE_OPTIONS.map((option) => (
                          <SelectItem key={option} value={String(option)}>
                            {option}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={currentPage <= 1 || skillsQuery.isLoading}
                    onClick={() =>
                      setCurrentPage((prev) => Math.max(1, prev - 1))
                    }
                  >
                    Previous
                  </Button>
                  <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    {totalCountInfo.hasKnownTotal
                      ? `Page ${currentPage} of ${totalPages}`
                      : `Page ${currentPage}`}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={!hasNextPage || skillsQuery.isLoading}
                    onClick={() => {
                      setCurrentPage((prev) =>
                        totalCountInfo.hasKnownTotal
                          ? Math.min(totalPages, prev + 1)
                          : prev + 1,
                      );
                    }}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </>
          )}

          {skillsQuery.error ? (
            <p className="text-sm text-rose-600">{skillsQuery.error.message}</p>
          ) : null}
          {packsQuery.error ? (
            <p className="text-sm text-rose-600">{packsQuery.error.message}</p>
          ) : null}
          {mutationError ? (
            <p className="text-sm text-rose-600">{mutationError}</p>
          ) : null}
        </div>
      </DashboardPageLayout>

      <SkillInstallDialog
        selectedSkill={selectedSkill}
        gateways={gateways}
        gatewayInstalledById={gatewayInstalledById}
        isGatewayStatusLoading={isGatewayStatusLoading}
        installingGatewayId={installingGatewayId}
        isMutating={isMutating}
        gatewayStatusError={gatewayStatusError}
        mutationError={mutationError}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedSkill(null);
          }
        }}
        onToggleInstall={(gatewayId, isInstalled) => {
          void handleGatewayInstallAction(gatewayId, isInstalled);
        }}
      />
    </>
  );
}
