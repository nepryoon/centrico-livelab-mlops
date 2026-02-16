# NOTE (staging)
This starter assumes your `services/inference/Dockerfile` builds a runnable FastAPI image exposing port 8000.

If your inference currently loads artifacts from `/artifacts`, you have two options:
1) **Bake artifacts into the image** (recommended for demo):
   - add a step like: `COPY artifacts/ /artifacts/` (ensure artifacts exist in the build context)
2) **Download artifacts at runtime** (S3) using task role permissions.

In this starter workflow we push a `bootstrap` tag too, so Terraform can create the ECS service before the first SHA-tag deployment.
