import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox, ProgressBar, usePoll } from "../components/common.jsx";

const TITLES = {
  graph_extract: "Extracting your knowledge graph",
  graph_build: "Building your knowledge graph",
  rag_ingest: "Indexing your documents",
  hybrid_rag_ingest: "Indexing hybrid knowledge-base documents",
  hybrid_ingest: "Processing hybrid knowledge base",
  add_data: "Adding data",
};

function JobProgress({ job, title }) {
  if (!job) {
    return (
      <div className="card" style={{ padding: 20 }}>
        <div className="muted">Loading {title.toLowerCase()} progress…</div>
      </div>
    );
  }

  const running = ["queued", "running"].includes(job.status);
  return (
    <div className="card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
      <div>
        <div className={`processing-status ${job.status}`}>
          <span className="processing-status-dot" />
          {job.status === "failed"
            ? "Action needs attention"
            : job.status === "succeeded"
              ? "Complete"
              : job.status === "cancelled"
                ? "Cancelled"
                : "In progress"}
        </div>
        <div style={{ fontSize: 18, fontWeight: 700 }}>{title}</div>
        <div className="muted">{job.source_file}</div>
      </div>
      <ProgressBar value={job.progress} label={`${title} progress`} />
      <div>
        {(job.steps || []).map((step, index) => {
          const state = job.status === "failed" && step.status === "running" ? "failed" : step.status;
          return (
            <div className="step" key={step.name}>
              <div className={`num ${state}`}>{index + 1}</div>
              <div style={{
                flexGrow: 1,
                fontWeight: state === "running" ? 600 : 400,
                color: state === "waiting" ? "var(--muted)" : undefined,
              }}>{step.name}</div>
              <div className="small" style={{
                color: state === "running" ? "var(--amber)" : "var(--muted)",
                fontWeight: state === "running" ? 600 : 400,
              }}>
                {state === "running" ? step.detail || "In progress" : state === "waiting" ? "Waiting" : step.detail}
              </div>
            </div>
          );
        })}
      </div>
      {job.status === "failed" && <div className="error" role="alert">{job.error}</div>}
      {job.status === "cancelled" && <div className="error">This job was cancelled.</div>}
      {running && (
        <div className="muted small">You can leave this page; progress is saved with the knowledge base.</div>
      )}
    </div>
  );
}

export default function Processing() {
  const { kb, jobId } = useParams();
  const [searchParams] = useSearchParams();
  const ragJobId = searchParams.get("ragJobId");
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [ragJob, setRagJob] = useState(null);
  const [kbInfo, setKbInfo] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => api(`/jobs/${jobId}`).then(setJob).catch(setError), [jobId]);
  const loadRagJob = useCallback(
    () => ragJobId && api(`/jobs/${ragJobId}`).then(setRagJob).catch(setError),
    [ragJobId],
  );
  const loadKb = useCallback(() => api(`/kbs/${kb}`).then(setKbInfo).catch(setError), [kb]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (ragJobId) loadRagJob(); }, [loadRagJob, ragJobId]);

  const running = !job || ["queued", "running"].includes(job.status);
  const ragRunning = !!ragJobId && (!ragJob || ["queued", "running"].includes(ragJob.status));
  const hybrid = job?.job_type === "hybrid_ingest" || !!ragJobId;
  const sequentialHybrid = job?.job_type === "hybrid_ingest";
  usePoll(load, 1500, running);
  usePoll(loadRagJob, 1500, ragRunning, [ragJobId]);
  usePoll(
    loadKb,
    1200,
    job?.job_type === "graph_build" && job.status === "succeeded" && hybrid && kbInfo?.status !== "ready",
    [kb],
  );

  useEffect(() => {
    if (job?.status !== "succeeded") return;
    if (job.job_type === "hybrid_ingest") {
      navigate(`/kbs/${kb}/review`, { replace: true });
      return;
    }
    if (job.job_type === "graph_extract") {
      if (!hybrid) navigate(`/kbs/${kb}/review`, { replace: true });
      return;
    }
    if (job.job_type === "graph_build" && hybrid) {
      if (kbInfo?.status === "ready" && ragJob?.status === "succeeded") {
        navigate(`/chat?kb=${kb}`, { replace: true });
      }
      return;
    }
    if (job.job_type === "graph_build" || job.job_type === "rag_ingest" || job.job_type === "add_data") {
      navigate(`/chat?kb=${kb}`, { replace: true });
    }
  }, [hybrid, job, kb, kbInfo, navigate, ragJob]);

  const cancel = async () => {
    try {
      const activeJobs = [job, ragJob].filter((candidate) => (
        candidate && ["queued", "running"].includes(candidate.status)
      ));
      await Promise.all(activeJobs.map((candidate) => (
        api(`/jobs/${candidate.id}/cancel`, { method: "POST" })
      )));
      load();
      loadRagJob();
    } catch (e) {
      setError(e);
    }
  };

  const reviewUrl = `/kbs/${kb}/review${ragJobId ? `?ragJobId=${ragJobId}` : ""}`;
  const canReview = ["graph_extract", "hybrid_ingest"].includes(job?.job_type) && job.status === "succeeded";
  const canOpenChat = hybrid && job?.job_type === "graph_build" && job.status === "succeeded"
    && kbInfo?.status === "ready" && ragJob?.status !== "succeeded";
  const active = running || ragRunning;

  return (
    <div className="page processing-page" style={{ alignItems: "center", justifyContent: "center", background: "#e9ebea" }}>
      <div className="card processing-card" style={{
        width: hybrid ? 760 : 600,
        maxWidth: "100%",
        padding: 32,
        display: "flex",
        flexDirection: "column",
        gap: 20,
      }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>
            {hybrid ? "Hybrid knowledge base processing" : TITLES[job?.job_type] || "Working"}
          </div>
          <div className="muted">{kb}</div>
        </div>

        {hybrid && !sequentialHybrid ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16 }}>
            <JobProgress job={job} title={TITLES[job?.job_type] || "Graph extraction"} />
            <JobProgress job={ragJob} title={TITLES.hybrid_rag_ingest} />
          </div>
        ) : (
          <JobProgress job={job} title={TITLES[job?.job_type] || "Working"} />
        )}

        <ErrorBox error={error} />
        {active && (
          <div className="notice" style={{ background: "var(--bg)", color: "#46524f", fontSize: 13 }}>
            {hybrid
              ? sequentialHybrid
                ? "Documents are indexed before graph extraction starts. You can leave this page; progress is saved with the knowledge base."
                : "Graph extraction and document indexing run independently. You can leave this page; both jobs continue in the background."
              : job?.job_type === "graph_extract"
                ? "You can leave this page. The knowledge base will show “Awaiting review” when extraction finishes."
                : "Progress is also shown in your workspace."}
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
          {active ? (
            <button className="btn sec" onClick={cancel}>Cancel active jobs</button>
          ) : (
            <Link className="btn sec" to="/workspace">Back to workspace</Link>
          )}
          {canReview && (
            <button className="btn" onClick={() => navigate(reviewUrl)}>Review graph</button>
          )}
          {canOpenChat && (
            <button className="btn" onClick={() => navigate(`/chat?kb=${kb}`)}>Chat with available data</button>
          )}
          {!hybrid && job?.job_type === "graph_extract" && (
            <button className="btn link" disabled={job.status !== "succeeded"}
                    onClick={() => navigate(`/kbs/${kb}/review`)}>Skip ahead to review</button>
          )}
        </div>
      </div>
    </div>
  );
}
