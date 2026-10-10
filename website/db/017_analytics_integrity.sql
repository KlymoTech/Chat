-- Database defense in depth for enumerated, non-identifying event vocabulary.
-- Additive, non-destructive and NOT VALID: preserves old rows until a separately
-- authorized data-quality review. NEW writes are checked immediately by Postgres.
BEGIN;
ALTER TABLE website_cms.analytics_events
 ADD CONSTRAINT website_analytics_event_action_pair
 CHECK (
   (event_name='content_view' AND action_key='page_view')
   OR (event_name='form_start' AND action_key='form_start')
   OR (event_name='navigation_click' AND action_key IN (
     'nav_home','nav_services','nav_about','nav_resources','nav_blog','nav_contact'))
   OR (event_name='cta_click' AND (
     action_key IN ('cta_contact','cta_services','cta_resources')
     OR action_key ~ '^cta_[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   ))
   OR (event_name='faq_open' AND
     action_key ~ '^faq_[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}_[0-9]{1,2}$')
 ) NOT VALID;
-- A DBA may VALIDATE CONSTRAINT only after checking any old invalid records;
-- never silently rewrite or delete existing metrics.
COMMIT;
