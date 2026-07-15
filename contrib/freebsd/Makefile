# New ports collection makefile for cloudflare-register

PORTNAME=	cloudflare-register
PORTVERSION=	0.2.0
CATEGORIES=	dns net python
# PyPI. NOTE: the sdist must be published to PyPI (make sdist + twine upload)
# before this port can fetch its distfile.
MASTER_SITES=	CHEESESHOP
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
		${PYTHON_PKGNAMEPREFIX}pyjwt>=2.9:www/py-pyjwt@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}bcrypt>=4.1:security/py-bcrypt@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}click>=8.1:devel/py-click@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}itsdangerous>=2.2:security/py-itsdangerous@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}python-multipart>=0.0.9:www/py-python-multipart@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}psutil>=6.0:sysutils/py-psutil@${PY_FLAVOR}

USES=		python:3.11+
USE_PYTHON=	autoplist concurrent pep517
USE_RC_SUBR=	cloudflare_ddns
NO_ARCH=	yes

.include <bsd.port.mk>
