# Illumio Cluster Manager - Installation Documentation

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Usage](#usage)
6. [Script Architecture](#script-architecture)
7. [Troubleshooting](#troubleshooting)
8. [Security Considerations](#security-considerations)
9. [Further Resources](#further-resources)

## Overview

The Illumio Cluster Manager is a tool designed to automate the installation and configuration of Illumio Core in Kubernetes environments. The main component, `install_illumio_final.py`, retrieves cluster credentials from HashiCorp Vault and uses them to install the Illumio Helm chart with the appropriate configuration values.

This script handles:
- Retrieving cluster secrets from HashiCorp Vault
- Validating the Helm chart before installation
- Creating Kubernetes namespaces if needed
- Installing the Illumio Helm chart with proper credentials
- Verifying the installation was successful

## Prerequisites

Before using this tool, ensure the following prerequisites are met:

### Required Software
- Python 3.6 or higher
- Kubernetes CLI (`kubectl`) installed and configured
- Helm 3.x installed
- Access to HashiCorp Vault with appropriate permissions

### Environment Configuration
1. Vault Authentication:
   - `SA_TOKEN` environment variable must be set with a valid service account token
   - `ENVIRONMENT` environment variable must be set to the target environment (e.g., `prod`, `dev`)

2. Vault URLs:
   - For production environments:
     - `STL_VAULT_LOGIN` and `PHX_VAULT_LOGIN` environment variables must be set to the Vault login URLs
   - For non-production environments:
     - `VAULT_LOGIN` environment variable must be set to the Vault login URL

3. Secrets Path:
   - `ILLUMIO_CLUSTER_SECRETS_PATH` environment variable should be set to the Vault path for Illumio secrets
   - `PCE_CREDS` environment variable must be set to the path for PCE API credentials

### Dependencies

Install the required Python dependencies:

```bash
pip install -r requirements.txt
```

The requirements.txt file includes:
```
requests
urllib3
```

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-organization/illumio-cluster-manager.git
   cd illumio-cluster-manager
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up the required environment variables:
   ```bash
   # Authentication token for Vault
   export SA_TOKEN="your-service-account-token"
   
   # Environment (prod, dev, etc.)
   export ENVIRONMENT="prod"
   
   # Vault URLs
   export STL_VAULT_LOGIN="https://vault.stl.example.com/v1/auth/kubernetes/login"
   export PHX_VAULT_LOGIN="https://vault.phx.example.com/v1/auth/kubernetes/login"
   
   # Secrets paths
   export PCE_CREDS="https://vault.example.com/v1/secret/data/pce/credentials"
   export ILLUMIO_CLUSTER_SECRETS_PATH="https://vault.example.com/v1/secret/data/illumio/clusters"
   ```

## Configuration

### Script Configuration Options

The `install_illumio_final.py` script accepts the following command-line arguments:

| Argument | Description | Default |
|----------|-------------|---------|
| `--cluster-name` | Name of the Kubernetes cluster | Required |
| `--chart-path` | Path to the Helm chart directory | Current directory (`.`) |
| `--namespace` | Kubernetes namespace to install into | `illumio-system` |
| `--values-file` | Path to values.yaml file | `values.yaml` |
| `--release-name` | Helm release name | `illumio` |
| `--registry` | Container registry to use | `registry.access.redhat.com/ubi9` |
| `--create-namespace` | Create namespace if it doesn't exist | `False` |
| `--debug` | Enable debug output | `False` |

### Helm Chart Values

The Illumio Helm chart is configured with the following key parameters:

| Parameter | Description | Source |
|-----------|-------------|--------|
| `cluster_id` | Cluster ID from PCE | Retrieved from Vault |
| `cluster_token` | Cluster Token from PCE | Retrieved from Vault |
| `cluster_code` | Code for C-VEN activation | Retrieved from Vault |
| `registry` | Container registry for images | Command-line argument |

Additional values can be configured in the values.yaml file:

- `containerRuntime`: Underlying container runtime engine
- `containerManager`: Underlying container management system
- `clusterMode`: Cluster mode setting
- `degradedModePolicyFail`: Degraded mode policy
- `enforceNodePortTraffic`: Enforce NodePort traffic setting

## Usage

### Basic Usage

To install Illumio in a Kubernetes cluster:

```bash
python install_illumio_final.py --cluster-name my-cluster
```

This will:
1. Retrieve cluster credentials from Vault
2. Install the Illumio Helm chart in the `illumio-system` namespace
3. Configure the deployment with the retrieved credentials

### Advanced Usage

For more control over the installation:

```bash
python install_illumio_final.py \
  --cluster-name my-cluster \
  --chart-path ./illumio-chart \
  --namespace illumio-system \
  --values-file custom-values.yaml \
  --release-name illumio-release \
  --registry registry.access.redhat.com/ubi9 \
  --create-namespace \
  --debug
```

### Example Workflow

1. **Prepare the environment**:
   ```bash
   # Set environment variables for Vault access
   export SA_TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
   export ENVIRONMENT="prod"
   export PCE_CREDS="https://vault.example.com/v1/secret/data/pce/credentials"
   export ILLUMIO_CLUSTER_SECRETS_PATH="https://vault.example.com/v1/secret/data/illumio/clusters"
   ```

2. **Validate Kubernetes access**:
   ```bash
   kubectl cluster-info
   ```

3. **Install Illumio**:
   ```bash
   python install_illumio_final.py \
     --cluster-name production-cluster \
     --create-namespace \
     --registry registry.example.com/illumio
   ```

4. **Verify the installation**:
   ```bash
   kubectl get pods -n illumio-system
   helm status illumio -n illumio-system
   ```

## Script Architecture

The `install_illumio_final.py` script is structured as follows:

### Main Components

1. **retrieve_cluster_secrets()**: Retrieves cluster credentials from Vault
2. **validate_helm_chart()**: Validates the Helm chart before installation
3. **install_illumio_helm_chart()**: Installs the Helm chart with the retrieved credentials
4. **main()**: Parses command-line arguments and orchestrates the installation process

### Dependencies

The script relies on the following modules:

- **bin.illumio.ejvault**: Provides functions for interacting with HashiCorp Vault
- **bin.illumio.ejconfig**: Contains configuration constants
- **bin.illumio.ejfile**: Provides file manipulation utilities

### Code Flow

1. The script begins by parsing command-line arguments.
2. It verifies that kubectl and Helm are installed.
3. It retrieves PCE credentials from Vault using `ejvault.get_pce_secrets()`.
4. It retrieves cluster-specific secrets from Vault.
5. If requested, it creates the specified Kubernetes namespace.
6. It validates the Helm chart.
7. It constructs and executes the Helm install command with the retrieved secrets.
8. It verifies the installation was successful.

## Troubleshooting

### Common Issues

#### Vault Authentication Failures

If you encounter Vault authentication failures:

1. Verify the `SA_TOKEN` environment variable is set correctly.
2. Ensure the service account has the necessary permissions in Vault.
3. Check that the Vault URL environment variables are correct for your environment.

Example error:
```
Failed to authenticate with Vault
```

Solution:
```bash
# Refresh the token
export SA_TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
```

#### Missing Secrets

If the script cannot find the required secrets:

1. Verify the cluster name is correct.
2. Check that the secrets exist in the specified Vault path.
3. Ensure the naming convention matches: `{cluster_name}_container_cluster_id`, etc.

Example error:
```
Missing required secrets in Vault: container_cluster_id, container_cluster_token
```

Solution:
- Use the Vault UI or CLI to verify the secrets exist
- Ensure the `ILLUMIO_CLUSTER_SECRETS_PATH` environment variable is set correctly

#### Helm Installation Failures

If the Helm installation fails:

1. Use the `--debug` flag to get more detailed output.
2. Check for Kubernetes API server connectivity issues.
3. Verify the values in the values.yaml file are correct.

Example error:
```
Error executing Helm command: Command '['helm', 'install', ...]' returned non-zero exit status 1
```

Solution:
- Check the Kubernetes cluster is accessible: `kubectl cluster-info`
- Verify the Helm chart is valid: `helm lint ./illumio-chart`
- Ensure the values.yaml file exists and is correctly formatted

### Logs

To enable detailed logging, use the `--debug` flag:

```bash
python install_illumio_final.py --cluster-name my-cluster --debug
```

## Security Considerations

### Secrets Management

- The script retrieves sensitive credentials from HashiCorp Vault.
- The credentials are stored in memory only during execution.
- No credentials are written to disk or logs.

### Best Practices

1. Use a dedicated service account with minimal permissions.
2. Regularly rotate the Vault authentication token.
3. Run the script in a secure environment with restricted access.
4. Do not store cluster credentials in the script or in environment variables.

## Further Resources

- [Illumio Core Documentation](https://docs.illumio.com/)
- [Helm Documentation](https://helm.sh/docs/)
- [HashiCorp Vault Documentation](https://www.vaultproject.io/docs)
- [Kubernetes Documentation](https://kubernetes.io/docs/home/)
