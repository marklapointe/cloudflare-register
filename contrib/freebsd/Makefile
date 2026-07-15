# New ports collection makefile for cloudflare-register

PORTNAME=	cloudflare-register
PORTVERSION=	0.2.0
CATEGORIES=	dns net python
MASTER_SITES=	https://pypi.org/packages/source/c/cloudflare-register/
PKGNAMEPREFIX=	${PYTHON_PKGNAMEPREFIX}
DISTNAME=	${PORTNAME}-${PORTVERSION}

MAINTAINER=	mark@cloudbsd.org
COMMENT=	Smart DynDNS service for Cloudflare with multi-zone, dual-stack, and state synchronization
WWW=		https://github.com/cloudbsdorg/cloudflare-register

LICENSE=	BSD3CLAUSE
LICENSE_FILE=	${WRKSRC}/LICENSE

BUILD_DEPENDS=	${PYTHON_PKGNAMEPREFIX}setuptools>=68:devel/py-setuptools@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}wheel>=0:devel/py-wheel@${PY_FLAVOR}
RUN_DEPENDS=	${PYTHON_PKGNAMEPREFIX}fastapi>=0.115:www/py-fastapi@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}uvicorn>=0.30:www/py-uvicorn@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}pydantic>=2.7:devel/py-pydantic@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}pydantic-settings>=2.4:devel/py-pydantic-settings@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}jinja2>=3.1:devel/py-jinja2@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}httpx>=0.27:net/py-httpx@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}bcrypt>=4.1:security/py-bcrypt@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}click>=8.1:devel/py-click@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}itsdangerous>=2.2:security/py-itsdangerous@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}python-multipart>=0.0.9:www/py-python-multipart@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}python-jose>=3.3:security/py-python-jose@${PY_FLAVOR}

USES=		python:3.11+
USE_PYTHON=	autoplist concurrent
USE_RC_SUBR=	cloudflare_ddns
NO_ARCH=	yes
SUB_LIST+=	PYTHON_PKGNAMEPREFIX=${PYTHON_PKGNAMEPREFIX} \
		PYTHON=${PYTHON_CMD}

PLIST_SUB+=	PYTHON_PKGNAMEPREFIX=${PYTHON_PKGNAMEPREFIX}

post-install:
	${MKDIR} ${STAGEDIR}${PREFIX}/etc/cloudflare-register
	${INSTALL_DATA} ${WRKSRC}/deploy/cloudflare-register.env.example \
		${STAGEDIR}${PREFIX}/etc/cloudflare-register/cloudflare-register.env.sample
	${INSTALL_DATA} ${WRKSRC}/LICENSE ${STAGEDIR}${PREFIX}/share/licenses/${PORTNAME}/LICENSE

.include <bsd.port.mk>
