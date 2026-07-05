// CourseLens CI pipeline (Jenkins).
//
// Same gate as .github/workflows/ci.yml: lint → compile → offline tests.
// Run a local Jenkins with:
//   docker run -p 8080:8080 -v jenkins_home:/var/jenkins_home jenkins/jenkins:lts
// then create a Pipeline job pointed at this repo ("Pipeline script from SCM").
pipeline {
    agent any

    environment {
        // Tests are fully offline — the dummy key only satisfies client construction.
        GROQ_API_KEY = 'dummy_ci_key'
    }

    options {
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
    }

    stages {
        stage('Setup') {
            steps {
                sh '''
                    python3 -m venv .venv
                    . .venv/bin/activate
                    pip install --quiet --upgrade pip
                    pip install --quiet -r requirements.txt pytest ruff
                '''
            }
        }
        stage('Lint') {
            steps { sh '. .venv/bin/activate && ruff check backend frontend tests' }
        }
        stage('Compile') {
            steps { sh '. .venv/bin/activate && python -m py_compile backend/*.py backend/ingest/*.py backend/evals/run_evals.py frontend/app.py' }
        }
        stage('Test') {
            steps { sh '. .venv/bin/activate && pytest -q' }
        }
    }

    post {
        failure { echo 'CI failed — do not merge.' }
    }
}
