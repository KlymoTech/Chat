import {test,expect} from "@playwright/test";
test("public site loads and navigation remains accessible without backend",async({page})=>{
  await page.goto("/");
  await expect(page.getByRole("navigation",{name:"Primary navigation"})).toBeVisible();
  await expect(page.getByRole("link",{name:"Services"})).toBeVisible();
  await expect(page.getByRole("link",{name:"Contact"})).toBeVisible();
  await page.getByRole("link",{name:"Services"}).first().click();
  await expect(page).toHaveURL(/\/services$/);
  await expect(page.locator("main")).toBeVisible();
});
test("optional analytics starts denied and rejection remains possible without the DB",async({page})=>{
  const recorded:string[]=[];
  page.on("request",request=>{
    if(request.url().includes("/api/analytics/events"))recorded.push(request.url());
  });
  await page.goto("/");
  await expect(page.getByRole("region",{name:"Privacy choices"})).toBeVisible();
  await page.getByRole("button",{name:"Reject optional"}).click();
  await expect(page.getByRole("region",{name:"Privacy choices"})).toHaveCount(0);
  const saved=await page.evaluate(()=>localStorage.getItem("website-consent-v1"));
  expect(saved).toContain('"analytics":false');
  expect(saved).toContain('"marketing":false');
  expect(recorded).toEqual([]);
  await page.getByRole("button",{name:"Privacy choices"}).last().click();
  await expect(page.getByRole("region",{name:"Manage privacy choices"})).toBeVisible();
});
test("owner APIs stay closed until identity and DB grants are activated",async({page,request})=>{
  const result=await request.get("/api/owner/pages");
  expect(result.status()).toBe(503);
  await page.goto("/owner");
  await expect(page.getByRole("heading",{name:"Owner CMS"})).toBeVisible();
  await expect(page.getByText(/activation is blocked/i)).toBeVisible();
});
test("retired content URL has no public redirect unless explicitly approved",async({request})=>{
  const response=await request.get("/content/retired-guide",{maxRedirects:0});
  expect(response.status()).toBe(404);
});
test("redirect management remains private and disabled by default",async({request})=>{
  const listing=await request.get("/api/owner/redirects");
  expect(listing.status()).toBe(503);
  const review=await request.post("/api/owner/redirects",{
    data:{sourcePath:"/content/old",targetPath:"/resources",reasonCode:"slug_change"},
  });
  expect(review.status()).toBe(503);
});
test("privacy rights remain owner-only and disabled by default",async({request})=>{
  const rights=await request.get("/api/owner/privacy/rights");
  expect(rights.status()).toBe(503);
  const denied=await request.post("/api/owner/privacy/rights",{
    data:{kind:"erasure"},headers:{"Origin":"http://127.0.0.1:3817"},
  });
  expect(denied.status()).toBe(503);
});
test("unconfigured private analytics and automation endpoints reveal no data",async({request})=>{
  const [analytics,automations]=await Promise.all([
    request.get("/api/owner/analytics"),request.get("/api/owner/automations"),
  ]);
  expect(analytics.status()).toBe(503);
  expect(automations.status()).toBe(503);
});
