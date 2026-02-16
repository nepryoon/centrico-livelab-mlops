locals {
  artifacts_bucket = "${var.app_prefix}-artifacts-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
}

data "aws_iam_policy_document" "gha_artifacts_rw" {
  statement {
    sid     = "ListArtifactsBucket"
    effect  = "Allow"
    actions = ["s3:ListBucket"]

    resources = [
      "arn:aws:s3:::${local.artifacts_bucket}"
    ]
  }

  statement {
    sid    = "RWArtifactsObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]

    resources = [
      "arn:aws:s3:::${local.artifacts_bucket}/*"
    ]
  }
}

resource "aws_iam_policy" "gha_artifacts_rw" {
  name   = "${var.app_prefix}-gha-artifacts-rw-staging"
  policy = data.aws_iam_policy_document.gha_artifacts_rw.json
}

resource "aws_iam_role_policy_attachment" "gha_artifacts_rw" {
  role       = aws_iam_role.gha_staging.name
  policy_arn = aws_iam_policy.gha_artifacts_rw.arn
}
