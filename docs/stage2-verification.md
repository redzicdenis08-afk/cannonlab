# Stage 2 verification

This pull request exists to force GitHub Actions to compile and validate the autonomous CannonLab Stage 2 implementation through a pull-request event.

Validation gates:

- Java 25 compilation
- Paper/Sakura API resolution
- WorldEdit integration compilation
- plugin JAR packaging
- scenario and PowerShell fixture presence

The local self-hosted physics run remains a separate gate after cloud compilation passes.
