#!/usr/bin/env bash
# Builds the image, deploys it as a Cloud Run Job, and wires up a Cloud
# Scheduler trigger that runs it every 48 hours.
#
# Prereqs (one-time, do manually):
#   - gcloud auth login / gcloud config set project <PROJECT_ID>
#   - Create a service account for Sheets writes, download its JSON key,
#     share each target Sheet with the service account's email.
#   - Store that key in Secret Manager:
#       gcloud secrets create sheets-sa-key --data-file=sheets-sa-key.json
#   - Create a GCS bucket for task YAMLs and upload the starter tasks/*.yaml:
#       gsutil mb gs://<PROJECT_ID>-tracker-tasks
#       gsutil cp tasks/*.yaml gs://<PROJECT_ID>-tracker-tasks/tasks/
#   - Create a dedicated invoker service account for Cloud Scheduler:
#       gcloud iam service-accounts create tracker-job-invoker

set -euo pipefail

PROJECT_ID="$(gcloud config get-value project)"
REGION="${REGION:-us-central1}"
REPO="${REPO:-amazon-tracker}"
JOB_NAME="${JOB_NAME:-amazon-tracker-job}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/amazon-tracker:latest"
TASKS_BUCKET="${TASKS_BUCKET:-${PROJECT_ID}-tracker-tasks}"
INVOKER_SA="tracker-job-invoker@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Building and pushing image: ${IMAGE}"
gcloud builds submit --tag "${IMAGE}" .

echo "Deploying/updating Cloud Run Job: ${JOB_NAME}"
gcloud run jobs deploy "${JOB_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --set-env-vars="TASKS_BUCKET=${TASKS_BUCKET},SHEETS_SA_KEY_PATH=/secrets/sheets-sa-key.json" \
  --set-secrets="/secrets/sheets-sa-key.json=sheets-sa-key:latest" \
  --max-retries=1 \
  --task-timeout=15m \
  --memory=1Gi \
  --cpu=1

echo "Creating/updating Cloud Scheduler job (every 48h)"
gcloud scheduler jobs create http "${JOB_NAME}-scheduler" \
  --location="${REGION}" \
  --schedule="0 6 */2 * *" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
  --http-method=POST \
  --oauth-service-account-email="${INVOKER_SA}" \
  || gcloud scheduler jobs update http "${JOB_NAME}-scheduler" \
  --location="${REGION}" \
  --schedule="0 6 */2 * *" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
  --http-method=POST \
  --oauth-service-account-email="${INVOKER_SA}"

echo "Done. Run once manually with:"
echo "  gcloud run jobs execute ${JOB_NAME} --region=${REGION}"
