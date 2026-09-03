# Configurations optionnelles

Ces fichiers ne servent **que** si la VM doit héberger elle-même son
reverse proxy et terminer le TLS.

## Vous avez déjà un nginx (ou Apache) frontal ?

**N'installez rien de ce répertoire.** Deux reverse proxies en cascade
n'apportent rien et compliquent le diagnostic de l'IP réelle du client.

La bonne configuration est alors :

```
Internet → nginx frontal (TLS) → VM:8000 (uvicorn)
```

Voir `deploy/nginx-frontend.conf` (à installer sur le frontal) et
`deploy/setup.sh` (à lancer sur la VM).

## `apache-post-generator.conf`

À utiliser uniquement si la VM est exposée directement à Internet et
qu'Apache doit y assurer le TLS et le proxy vers uvicorn. Dans ce cas,
uvicorn écoute sur `127.0.0.1:8000` et Apache est le seul point d'entrée.
