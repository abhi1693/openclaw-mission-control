"use client";

export const dynamic = "force-dynamic";

import { useTranslations } from 'next-intl';

// 注意：实际的 dashboard 页面代码保持不变
// 这里只是一个 i18n 包装示例
// 完整的 dashboard 页面需要从原文件迁移

export default function DashboardPage() {
  const t = useTranslations('Dashboard');
  const common = useTranslations('Common');
  
  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold">{t('title')}</h1>
      <p className="mt-4 text-gray-600">{t('welcome')}</p>
      <div className="mt-8">
        <p>{common('loading')}</p>
      </div>
    </div>
  );
}
