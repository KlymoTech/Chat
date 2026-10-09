// Non-deploying certification preflight. This is NOT a signing/approval pipeline.
// Production qualification requires an isolated Jenkins controller, protected
// credentials, reviewed agents, durable evidence and a separately audited issuer.
// The publisher contract is unit-tested here; this preflight never calls it
// with a real AWS identity or submits artifacts to S3.
pipeline {
  agent { label 'northstar-qualification' }
  options {
    timeout(time: 35, unit: 'MINUTES')
    disableConcurrentBuilds()
    skipDefaultCheckout()
    timestamps()
  }
  environment {
    APP_ENV = 'test'
    PYTHONDONTWRITEBYTECODE = '1'
  }
  stages {
    stage('Confirm isolated branch') {
      steps {
        script {
          if (env.BRANCH_NAME != 'feature/northstar-adaptive-architecture-20261008') {
            error('Qualification preflight is restricted to the Northstar feature branch')
          }
        }
      }
    }
    stage('Checkout reviewed source') {
      steps {
        checkout scm
      }
    }
    stage('Static and unit qualification') {
      steps {
        dir('backend') {
          sh '''
            set -eu
            uv sync --all-groups --locked
            uv run ruff check src/northstar_api/modules/platform_runtime tests/test_platform_notification_qualification_governance.py tests/test_platform_notification_qualification_api.py tests/test_platform_notification_qualification_ingestion.py tests/test_platform_aws_jenkins_evidence_publisher.py
            uv run pytest -q tests/test_platform_notification_qualification_governance.py tests/test_platform_notification_qualification_api.py tests/test_platform_notification_qualification_ingestion.py tests/test_platform_queue_notification_worker_qualification.py tests/test_platform_aws_jenkins_evidence_publisher.py
          '''
        }
      }
    }
  }
  post {
    always {
      echo 'This preflight never issues signing proofs, enables workers, deploys, or grants approval.'
    }
  }
}
