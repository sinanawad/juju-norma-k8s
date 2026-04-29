# Juju 4.0.x: Deploying local charm with OCI resource fails — "resource not found" (regression from incomplete #21456 fix)

### Description

Deploying a local charm with an OCI image resource fails 100% of the time on Juju 4.0.x (tested on 4.0.4 and 4.0.6). This is a continuation of #21456 — the fix in PR #21775 resolved the `ApplicationNotFound` check in the HTTP upload handler, but the `GetResource` call immediately after still fails because the service layer queries the wrong view.

```
$ juju deploy ./juju-norma-k8s_amd64.charm --resource juju-norma-image=ghcr.io/sinanawad/juju-norma:latest
Located local charm "juju-norma-k8s", revision 0
ERROR resource "juju-norma-image": Put https://127.0.0.1:39007/model/.../applications/juju-norma-k8s/resources/juju-norma-image?pendingid=1a6a8223-d58b-4a79-82fb-f35e62efaac3: resource juju-norma-image of application juju-norma-k8s not found
```

Charmhub deploys work fine. Only local charm deploys with `--resource` are affected.

### Juju version

4.0.6 (also reproduced on 4.0.4)

### Cloud

Kubernetes (microk8s)

### Expected behaviour

`juju deploy ./local.charm --resource foo=registry/image:tag` should succeed — the pending resource created by `AddPendingResources` should be found by the upload handler.

### Reproduce / Test

```bash
# 1. Bootstrap a K8s controller on Juju 4.0.x
juju bootstrap microk8s k8s

# 2. Create a model
juju add-model test microk8s -c k8s

# 3. Deploy any local charm with an OCI resource
juju deploy ./my-charm_amd64.charm --resource my-image=ghcr.io/org/image:latest
# ERROR resource "my-image": Put https://.../resources/my-image?pendingid=<uuid>: resource my-image of application my-charm not found
#                                                                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#                                                                                   This is the bug — pending resource exists but can't be found
```

This fails on every attempt, not intermittently.

### Root Cause

The deploy flow for local charms with OCI resources is:

1. Client calls `AddPendingResources` → server inserts into `resource` table + `pending_application_resource` table → returns UUID
2. Client uploads resource blob via HTTP PUT with `?pendingid=<uuid>`
3. Server upload handler (`apiserver/internal/handlers/resources/resources.go`) calls `resourceService.GetResource(ctx, uuid)`

PR #21775 fixed step 3 so that `ApplicationNotFound` no longer short-circuits the handler. But immediately after, at line 274, the handler calls `GetResource` which delegates to `Service.GetResource` in `domain/resource/service/resource.go:364`:

```go
func (s *Service) GetResource(ctx context.Context, resourceUUID coreresource.UUID) (coreresource.Resource, error) {
    // ...
    return s.st.GetApplicationResource(ctx, resourceUUID)  // <<<<< BUG: queries v_application_resource
}
```

`GetApplicationResource` queries the `v_application_resource` view, which joins `resource` → `application_resource` → `application`. For pending resources, there is **no row in `application_resource`** (the application doesn't exist yet), so the query returns zero rows → `ResourceNotFound`.

The state layer already has the correct method — `State.GetResource()` (at `domain/resource/state/resource.go:605`) which queries `v_resource` with LEFT JOINs and works without an application link.

### Suggested Fix

One-line change in `domain/resource/service/resource.go`:

```diff
 func (s *Service) GetResource(
     ctx context.Context,
     resourceUUID coreresource.UUID,
 ) (coreresource.Resource, error) {
     if err := resourceUUID.Validate(); err != nil {
         return coreresource.Resource{}, errors.Errorf("resource id: %w", err)
     }
-    return s.st.GetApplicationResource(ctx, resourceUUID)
+    return s.st.GetResource(ctx, resourceUUID)
 }
```

`State.GetResource` is already defined, already in the `State` interface (line 84), and already used elsewhere (e.g. `StoreResource` at line 402). It queries `v_resource` with LEFT JOINs to `application_resource` and `application`, so it returns the resource regardless of whether the application exists yet.

Verified: this fix resolves the issue — local charm deploys with OCI resources succeed after applying it.

### Notes & References

- Original issue: #21456
- Partial fix (facade layer): PR #21612
- Partial fix (HTTP handler): PR #21775
- Affected file: `domain/resource/service/resource.go:371`
- Fix file: same, one-line change
