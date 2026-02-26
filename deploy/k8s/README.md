# Kubernetes Deployment (Baseline)

Apply in this order:

```bash
kubectl apply -f deploy/k8s/pvc.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/deployment-team-runtime.yaml
kubectl apply -f deploy/k8s/deployment-controlplane.yaml
kubectl apply -f deploy/k8s/service-controlplane.yaml
kubectl apply -f deploy/k8s/hpa-team-runtime.yaml
```

Expose the control-plane service via ingress or port-forward:

```bash
kubectl port-forward service/agentx-controlplane 28880:80
```

Then open: `http://127.0.0.1:28880/panel`
