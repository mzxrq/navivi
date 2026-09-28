import type { LinguiConfig } from '@lingui/conf';
import { formatter } from '@lingui/format-po';

const config: LinguiConfig = {
  locales: ["en", "ja"],
  sourceLocale: "en",
  catalogs: [
    {
      path: "src/locales/{locale}/messages",
      include: ["src/**/*.{ts,tsx}", "src/components/**/*.{ts,tsx}"],
    },
  ],
  format: formatter(),
  compileNamespace: "es",
};

export default config;

