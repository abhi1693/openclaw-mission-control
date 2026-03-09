export type Locale = 'en' | 'zh';

export const defaultLocale: Locale = 'zh';
export const locales: Locale[] = ['en', 'zh'];

export const localeLabels: Record<Locale, string> = {
  en: 'English',
  zh: '中文',
};

export const localeFlags: Record<Locale, string> = {
  en: '🇺🇸',
  zh: '🇨🇳',
};
