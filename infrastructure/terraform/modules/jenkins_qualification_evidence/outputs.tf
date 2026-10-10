output "evidence_bucket_name" {
  description = "Versioned compliance-locked bucket name."
  value       = aws_s3_bucket.evidence.id
}

output "evidence_bucket_arn" {
  description = "Exact evidence bucket ARN."
  value       = aws_s3_bucket.evidence.arn
}

output "evidence_kms_key_arn" {
  description = "Dedicated customer-managed KMS key ARN for S3 evidence encryption."
  value       = aws_kms_key.evidence.arn
}

output "publisher_role_arn" {
  description = "Scoped publishing role to assume from the reviewed Jenkins agent."
  value       = aws_iam_role.publisher.arn
}

output "evidence_prefix" {
  description = "Only this object prefix is available to the publisher role."
  value       = "evidence/"
}
