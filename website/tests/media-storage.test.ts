import {afterEach,describe,expect,it,vi} from "vitest";
vi.mock("server-only",()=>({}));
import {readQuarantineStoreConfig} from "../src/lib/media-storage";

function config():NodeJS.ProcessEnv{
  return {
    WEBSITE_MEDIA_UPLOAD_ENABLED:"true",
    WEBSITE_MEDIA_STORAGE_ENDPOINT:"https://storage.company.testdomain/",
    WEBSITE_MEDIA_STORAGE_BUCKET:"website-private-quarantine",
    WEBSITE_MEDIA_STORAGE_REGION:"us-east-1",
    WEBSITE_MEDIA_STORAGE_ACCESS_KEY_ID:"test-access-key",
    WEBSITE_MEDIA_STORAGE_SECRET_ACCESS_KEY:"test-secret-key-of-more-than-16-bytes",
    NODE_ENV:"production",
  };
}
afterEach(()=>vi.unstubAllEnvs());
describe("operator controlled quarantine object store",()=>{
  it("requires opt-in and complete private credentials",()=>{
    expect(readQuarantineStoreConfig({...config(),WEBSITE_MEDIA_UPLOAD_ENABLED:"false"})).toBeNull();
    expect(readQuarantineStoreConfig({...config(),WEBSITE_MEDIA_STORAGE_SECRET_ACCESS_KEY:""})).toBeNull();
    expect(readQuarantineStoreConfig(config())?.bucket).toBe("website-private-quarantine");
  });
  it("requires production TLS and blocks private IP/metadata hosts",()=>{
    for(const endpoint of [
      "http://storage.company.testdomain/",
      "https://127.0.0.1/",
      "https://10.0.0.1/",
      "http://169.254.169.254/",
      "https://localhost/",
      "https://storage.internal/",
      "https://storage.company.testdomain/unexpected-path",
      "https://person:password@storage.company.testdomain/",
    ])expect(readQuarantineStoreConfig({...config(),WEBSITE_MEDIA_STORAGE_ENDPOINT:endpoint})).toBeNull();
  });
  it("allows intentionally configured development-only loopback MinIO",()=>{
    const setting={...config(),NODE_ENV:"development",WEBSITE_MEDIA_STORAGE_LOCAL_DEV:"true",
      WEBSITE_MEDIA_STORAGE_ENDPOINT:"http://127.0.0.1:9000/"};
    expect(readQuarantineStoreConfig(setting)?.endpoint).toBe("http://127.0.0.1:9000");
    expect(readQuarantineStoreConfig({...setting,NODE_ENV:"production"})).toBeNull();
  });
});
