#!/usr/bin/env bash
# setup-storage.sh — Helper for configuring cloud storage backends.
set -euo pipefail

BACKEND="${1:-}"

usage() {
    echo "Usage: $0 [gcs|s3]"
    echo "  gcs  — Create GCS bucket and service account"
    echo "  s3   — Create AWS S3 bucket and IAM policy"
    exit 1
}

setup_gcs() {
    echo "=== GCS Setup ==="
    command -v gcloud >/dev/null 2>&1 || { echo "gcloud CLI not found."; exit 1; }
    read -r -p "GCS bucket name: " BUCKET_NAME
    read -r -p "GCP project ID: " PROJECT_ID
    read -r -p "Service account name [ghost-narrator-tts]: " SA_NAME
    SA_NAME="${SA_NAME:-ghost-narrator-tts}"
    gcloud storage buckets create "gs://$BUCKET_NAME" --project="$PROJECT_ID" --uniform-bucket-level-access
    gcloud iam service-accounts create "$SA_NAME" --project="$PROJECT_ID" --description="Ghost Narrator TTS"
    SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
    gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" --member="serviceAccount:$SA_EMAIL" --role="roles/storage.objectAdmin"
    KEY_FILE="${SA_NAME}-key.json"
    gcloud iam service-accounts keys create "$KEY_FILE" --iam-account="$SA_EMAIL"
    echo ""
    echo "=== Add to .env ==="
    echo "STORAGE_BACKEND=gcs"
    echo "GCS_BUCKET_NAME=$BUCKET_NAME"
    echo "GCS_SERVICE_ACCOUNT_KEY_PATH=/run/secrets/${KEY_FILE}"
}

setup_s3() {
    echo "=== AWS S3 Setup ==="
    command -v aws >/dev/null 2>&1 || { echo "AWS CLI not found."; exit 1; }
    read -r -p "S3 bucket name: " BUCKET_NAME
    read -r -p "AWS region [us-east-1]: " REGION
    REGION="${REGION:-us-east-1}"
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION" \
        $([ "$REGION" != "us-east-1" ] && echo "--create-bucket-configuration LocationConstraint=$REGION")
    aws s3api put-public-access-block --bucket "$BUCKET_NAME" \
        --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
    echo ""
    echo "=== Add to .env ==="
    echo "STORAGE_BACKEND=s3"
    echo "S3_BUCKET_NAME=$BUCKET_NAME"
    echo "AWS_REGION=$REGION"
}

case "$BACKEND" in
    gcs) setup_gcs ;;
    s3)  setup_s3 ;;
    *)   usage ;;
esac
