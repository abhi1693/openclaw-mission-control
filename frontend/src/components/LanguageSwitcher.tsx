'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useRouter, usePathname } from 'next/navigation';
import { localeLabels, locales, type Locale } from '@/i18n/config';

export function LanguageSwitcher() {
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const t = useTranslations('Settings');

  const switchLocale = (newLocale: Locale) => {
    // 替换 URL 中的语言前缀
    const pathWithoutLocale = pathname.replace(/^\/(en|zh)/, '') || '/';
    const newPath = `/${newLocale}${pathWithoutLocale}`;
    router.push(newPath);
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-gray-400">{t('language')}:</span>
      <select
        value={locale}
        onChange={(e) => switchLocale(e.target.value as Locale)}
        className="bg-gray-800 text-white text-sm px-3 py-1.5 rounded border border-gray-600 hover:border-gray-500 focus:outline-none focus:border-blue-500 transition-colors cursor-pointer"
      >
        {locales.map((loc) => (
          <option key={loc} value={loc}>
            {localeLabels[loc]}
          </option>
        ))}
      </select>
    </div>
  );
}
