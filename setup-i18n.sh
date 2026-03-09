#!/bin/bash
# i18n setup script for openclaw-mission-control

cd /root/openclaw-mission-control

echo "=== Adding files to git ==="
git add .

echo "=== Committing changes ==="
git commit -m "feat(i18n): add multi-language support (en/zh)

- Add next-intl for internationalization
- Create translation files for English and Chinese
- Add LanguageSwitcher component
- Configure Next.js i18n routing with middleware
- Add locale-aware layout and pages
- Add LanguageSwitcher to DashboardSidebar
- Support language switching between EN/ZH"

echo "=== Pushing to GitHub ==="
git push origin feature/i18n

echo "=== Done! ==="
echo "Check your PR at: https://github.com/logorun/openclaw-mission-control/pulls"
