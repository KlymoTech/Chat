#!/usr/bin/env node
/**
 * Read-only production security preflight; no migrations and no writes.
 * Use a disposable staging environment with the SAME grants as production.
 * This deliberately fails until real least-privilege roles/RLS are provisioned.
 */
import {Pool} from "pg";
const url=process.env.WEBSITE_SECURITY_VERIFY_DATABASE_URL;
if(!url || process.env.WEBSITE_SECURITY_VERIFY_ALLOW!=="true"){
  console.error("Explicit security verification DB URL and opt-in required");
  process.exitCode=2;
}else{
  const pool=new Pool({connectionString:url,max:1,connectionTimeoutMillis:4000,query_timeout:5000});
  const failed=[];
  try{
    const who=await pool.query(
      `SELECT current_user AS role_name, r.rolsuper AS superuser,
              r.rolbypassrls AS bypass_rls,r.rolcreaterole AS create_role
         FROM pg_roles r WHERE r.rolname=current_user`);
    if(who.rowCount!==1)throw new Error("Cannot resolve DB identity");
    const role=who.rows[0];
    if(role.superuser||role.bypass_rls||role.create_role)
      failed.push("Runtime role must not be superuser, bypass RLS or create roles");
    const reader=process.env.WEBSITE_SECURITY_VERIFY_ROLE;
    if(!["public-cms-reader","owner-editor"].includes(reader))
      throw new Error("Choose public-cms-reader or owner-editor");
    const tables=[
      "pages","page_revisions","lead_submissions","audit_events","outbox",
      "media_assets","consent_choices","analytics_events",
      "automation_definitions","automation_versions",
      "automation_internal_runs","automation_run_steps","automation_internal_tasks",
      "privacy_rights_cases","privacy_rights_history",
      "content_redirects",
    ];
    if(reader==="public-cms-reader"){
      const access=await pool.query(
        `SELECT has_table_privilege(current_user,
                 'website_cms.public_published_pages','SELECT') AS can_read`);
      if(!access.rows[0]?.can_read)failed.push("Reader lacks approved public CMS view");
      if(process.env.WEBSITE_REDIRECT_PUBLIC_ENABLED==="true"){
        const mapping=await pool.query(
          "SELECT has_table_privilege(current_user,"+
          "'website_cms.public_approved_content_redirects','SELECT') AS can_read");
        if(!mapping.rows[0]?.can_read)
          failed.push("Reader lacks approved public redirect security-barrier view");
      }
      for(const table of tables){
        const result=await pool.query(
          "SELECT has_table_privilege(current_user,$1,'SELECT') AS can_read, "+
          "has_table_privilege(current_user,$1,'INSERT') AS can_insert, "+
          "has_table_privilege(current_user,$1,'UPDATE') AS can_update, "+
          "has_table_privilege(current_user,$1,'DELETE') AS can_delete",
          ["website_cms."+table]);
        if(Object.values(result.rows[0]).some(Boolean))
          failed.push("Public reader may access private table "+table);
      }
    }else{
      const res=await pool.query(
        `SELECT c.relname,c.relrowsecurity AS rls_enabled,
                c.relforcerowsecurity AS force_rls
           FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='website_cms'
            AND c.relname=ANY($1::text[])`,[tables]);
      const byName=new Map(res.rows.map(x=>[x.relname,x]));
      for(const table of tables){
        const record=byName.get(table);
        if(!record||!record.rls_enabled||!record.force_rls)
          failed.push("Tenant table requires enabled and forced RLS: "+table);
      }
    }
    console.log(JSON.stringify({roleMode:reader,checksPassed:failed.length===0,
      denied:failed}));
    if(failed.length)process.exitCode=1;
  }catch(error){
    console.error("DB security preflight failed:",error?.code??"unavailable");
    process.exitCode=1;
  }finally{await pool.end();}
}
