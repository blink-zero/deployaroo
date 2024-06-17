FROM python:3.9

ENV TZ="Australia/Sydney"
WORKDIR /home/project/app
COPY requirements.txt /home/project/app
RUN pip3 install -r requirements.txt
RUN apt-get update
RUN apt-get install -y sshpass

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y python3-pip sshpass git openssh-client libhdf5-dev libssl-dev libffi-dev && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean
    
RUN pip3 install --upgrade pip cffi && \
    pip install ansible==7.5.0 && \
    pip install mitogen==0.2.10 ansible-lint==6.15.0 jmespath && \
    pip install --upgrade pywinrm && \
    rm -rf /root/.cache/pip

RUN mkdir /ansible && \
    mkdir -p /etc/ansible && \
    echo 'localhost' > /etc/ansible/hosts

# Set the command to run your application
CMD [ "gunicorn", "-w", "10", "-b", ":8000", "run:app", "--timeout", "3600" ]

COPY . /home/project/app
