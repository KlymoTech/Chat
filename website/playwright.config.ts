import {defineConfig,devices} from "@playwright/test";
export default defineConfig({
  testDir:"./tests/e2e",
  timeout:30000,
  fullyParallel:false,
  retries:0,
  workers:1,
  use:{
    baseURL:"http://127.0.0.1:3817",
    trace:"retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer:{
    command:"npm run start -- -p 3817",
    url:"http://127.0.0.1:3817",
    reuseExistingServer:false,
    timeout:120000,
    env:{
      NODE_ENV:"production",
      WEBSITE_CMS_OWNER_API_ENABLED:"false",
      WEBSITE_CONSENT_RECORDS_ENABLED:"false",
      WEBSITE_ANALYTICS_COLLECTION_ENABLED:"false",
      WEBSITE_MEDIA_PUBLIC_DELIVERY_ENABLED:"false",
      NEXT_PUBLIC_SITE_APPROVED:"false",
    },
  },
  reporter:[["list"]],
});
