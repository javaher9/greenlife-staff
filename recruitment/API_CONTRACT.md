# Recruitment API (phase 1)
All routes under `/management/recruitment/`. Namespace `recruitment`; dashboard route name `dashboard`, data name `data`.
Page context `api_root` = `/management/recruitment/api/`, `can_approve` bool. Template `recruitment/dashboard.html`.
All responses `{ok:true,...}` or `{ok:false,error:'Persian message',errors:{field:[messages]}}`. CSRF required; mutations POST only. Support FormData and JSON.

GET `api/` => `jobs`, `applications`, `ads`, `staff`, `branches`, `countries`, `choices`, `stats`, `can_approve`, `current_user_id`.
`choices` map keys organizations, job_statuses, stages, sources, ad_statuses (all arrays `{value,label}`).
Staff `{id,name}`, branches `{id,name,country}`, countries `{id,name,code}`.
Job keys: id,title,organization,organization_label,country,country_name,branch,branch_name,headcount,description,requirements,expected_outcomes,location,shift,benefits,criteria [{label,weight}],salary_min,salary_max,budget_approved,requires_executive_approval,owner,owner_name,status,status_label,target_date,application_count,created_at.
Application summary keys: id,name,phone,job,job_title,organization,branch,branch_name,country,source,source_label,stage,stage_label,owner,owner_name,next_action,next_action_at,interview_at,requested_salary,offered_salary,review_required,review_reason,pending_stage,score (null until authorized independent evaluation disclosure),evaluation_count,created_at,updated_at.
Ad keys: id,job,job_title,source,source_label,title,body,status,status_label,url,cost,external_id,expires_at.
Stats: active_jobs,new_applications,overdue,interviews_today,needs_approval,probation.

POST `api/jobs/` creates, POST `api/jobs/<id>/` action=save updates. Fields same Job keys excluding derived labels. Required title, country, owner; organization clinic default; headcount1; status draft. Criteria JSON array [{label,weight}] positive weights sum100, default 4 items weights40/25/20/15; may send JSON-string in FormData. salary values integer toman or empty. Dates YYYY-MM-DD. Missing optional values empty/default. For update send all form values. `action=approve_budget` executive only, optional note.
Returns `{ok:true,job:{...}}`.

POST `api/applications/` creates. Required name,phone,job,owner,next_action,next_action_at. Optional email,city,resume_text,resume (PDF file <=5MB),source,source_detail,requested_salary,notes. Phone Persian/Arabic digits normalized. Same phone per country reuses Candidate but each job application independent; duplicate same job returns400.
GET `api/applications/<id>/` => `{ok:true,application:{...}}`. Detail extends summary with candidate {id,name,phone,email,city,resume_text,resume_name,resume_url}, job_detail {full job},source_detail,interview_location,decision_reason,start_date,probation_review_at,probation_outcome,approved_by,approved_at,evaluations [{id,reviewer,reviewer_name,scores [{label,weight,score}],total,evidence,recommendation,updated_at}],evaluations_hidden,activities [{id,kind,text,actor_name,created_at,changes}]. Evaluation details and scores only shown executive or after caller submits own evaluation.
POST `api/applications/<id>/` actions:
- `update`: stage,owner,next_action,next_action_at,interview_at,interview_location,requested_salary,offered_salary,decision_reason,start_date,probation_review_at,source,source_detail. Send full form fields. For rejection/withdrawal/talent/salary_declined decision_reason required; talent also requires followup. Active stages require owner,next_action,due. Out-of-budget offer or important hire queues executive approval; strong candidate rejection queues instead of final rejection. Server chooses pending_stage. Returns full detail.
- `note`: text required (max5000)
- `evaluate`: scores JSON numeric array [0..100] matching job.criteria order (JSON string accepted), evidence required, recommendation advance|review|decline. Weighted total; immutable criteria snapshot stored with scores. Reviews can be revised by their author, with audit.
- `approve`: executive only; decision approve|return, text required. Approve applies pending_stage if any; return leaves decision stage. Returns full detail.
- `probation`: probation_outcome required, probation_review_at optional, start_date optional. Does not automatically mark hired.

GET `api/applications/<id>/resume/` authenticated attachment download (PDF); no public media.
POST `api/ads/` / `api/ads/<id>/`: required job,title,body; source,status,url,cost,external_id,expires_at optional. active requires actual http(s) url. Registers publication records ONLY, never posts externally. Returns `{ok:true,ad:{...}}`.
Server no delete endpoint, no public forms or SMS sending in phase1. Lists are country-scoped. Query args q/job/stage/source/owner/organization/branch optionally filter applications, jobs context still all scoped jobs.

## Concurrency and identity safety
Existing job save/approve_budget and application update/approve/probation require `expected_updated_at` exact returned record `updated_at`; mismatches409. Reload detail before retrying. Job includes updated_at. Notes/evaluation independent writes do not need version. Probation can be recorded only after started/probation/hired, and start_date cannot be cleared. Reused phone with different name rejects400; same name reuses existing identity without overwriting profile or CV; creation response has candidate_reused bool.

GET api/jobs/<id>/ returns {ok,job} and job.activities (latest100 job-level events with actor_name,created_at,kind,text,changes). Stats needs_approval counts applications only; pending_budgets counts jobs. GET api/ supports view=followups|onboarding|talent and quick=today|overdue|review|new before pagination (300/page). Independent evaluation spread >=25 across >=2 reviewers queues review_required without changing hiring stage. New evaluation invalidates any prior executive approval and queues review.

Candidate detail includes `candidate.updated_at`. POST application detail `action=candidate_update` accepts name,email,city,resume_text,optional resume PDF and requires `expected_candidate_updated_at` matching current candidate.updated_at. Phone remains immutable (different submitted value400). Missing PDF preserves file; uploaded PDF replaces it. Candidate information is shared across that person's applications in the same country; every associated application receives an audit event. Stage approval is explicitly scoped by `approved_stage`; acknowledging a review at an early stage never authorizes a later out-of-budget offer.
