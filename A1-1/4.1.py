# VSCode에 Python 확장(Extension)을 설치한다.
#  VSCode에 Korean Language Pack을 설치한다. (선택)

#  터미널에서 Python 버전을 확인한다. (Python 3.10 이상)
# PS C:\Users\user\Desktop\A1-1\AI> python --version
# Python 3.13.14


#  간단한 print("Hello") 코드를 작성하고 실행해본다.
print("Hello")

#  Git 버전을 확인한다.
# S C:\Users\user\Desktop\A1-1\AI> git config --list
# diff.astextplain.textconv=astextplain
# filter.lfs.clean=git-lfs clean -- %f
# filter.lfs.smudge=git-lfs smudge -- %f
# filter.lfs.process=git-lfs filter-process
# filter.lfs.required=true
# http.sslbackend=openssl
# http.sslcainfo=C:/Program Files/Git/mingw64/etc/ssl/certs/ca-bundle.crt
# core.autocrlf=true
# core.fscache=true
# core.symlinks=false
# pull.rebase=false
# credential.helper=manager
# credential.https://dev.azure.com.usehttppath=true
# init.defaultbranch=master
# user.name=Song0Hwi
# user.email=iamsongyounghwi@gmail.com
# core.repositoryformatversion=0
# core.filemode=false
# core.bare=false
# core.logallrefupdates=true
# core.symlinks=false
# core.ignorecase=true
# remote.origin.url=https://github.com/Song0Hwi/AI.git
# remote.origin.fetch=+refs/heads/*:refs/remotes/origin/*
# branch.main.remote=origin
# branch.main.merge=refs/heads/main
# branch.main.vscode-merge-base=origin/main

#  Git 사용자 정보(이름, 이메일)를 설정한다.
# PS C:\Users\user\Desktop\A1-1  \AI> git config user.name 
# Song0Hwi
# PS C:\Users\user\Desktop\A1-1\AI> git config user.email
# iamsongyounghwi@gmail.com


#  기본 브랜치 이름을 main으로 설정한다.
# PS C:\Users\user\Desktop\A1-1\AI> git config --global init.defaultBranch main
# PS C:\Users\user\Desktop\A1-1\AI> git branch
# * main


#  VSCode에서 GitHub 계정으로 로그인하고 연동이 정상적으로 되었는지 확인한다.
# PS C:\Users\user\Desktop\A1-1\AI> git remote -v
# origin  https://github.com/Song0Hwi/AI.git (fetch)
# origin  https://github.com/Song0Hwi/AI.git (push)


