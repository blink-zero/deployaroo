Prism.languages.ansible = {
    comment: /#.*/,
    timestamp: /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}/,
    pid: /p=\d+/,
    user: /u=[\w-]+/,
    ansible: /n=ansible/,
    keyword: /\b(?:PLAY|TASK|ok|fatal|changed|unreachable|skipped|rescued|ignored|FAILED|failed|WARNING|skipping)\b/,
    string: /("|')(?:\\?.)*?\1/,
    variable: /\{\{.*?\}\}/,
    boolean: /\b(?:true|false)\b/,
    number: /\b\d+\b/,
    operator: /[-+=]=?|!=|\*\*?|\/[\/=]?|<[<=]?|>[>=]?|&&|\|\|?|!|\?\.\.\.|\[|\]/,
    punctuation: /[{}[\];(),.:]/,
  };
  
  Prism.hooks.add('wrap', function(env) {
    if (env.type === 'timestamp') {
      env.content = `<span class="ansible-timestamp">${env.content}</span>`;
    } else if (env.type === 'pid') {
      env.content = `<span class="ansible-pid">${env.content}</span>`;
    } else if (env.type === 'user') {
      env.content = `<span class="ansible-user">${env.content}</span>`;
    } else if (env.type === 'ansible') {
      env.content = `<span class="ansible-ns">${env.content}</span>`;
    } else if (env.type === 'keyword') {
      if (env.content === 'fatal' || env.content === 'FAILED') {
        env.content = `<span class="ansible-keyword-fatal">${env.content}</span>`;
      } else if (env.content === 'WARNING') {
        env.content = `<span class="ansible-keyword-warning">${env.content}</span>`;
      } else if (env.content === 'TASK') {
        env.content = `<span class="ansible-keyword-task">${env.content}</span>`;
      } else {
        env.content = `<span class="ansible-keyword">${env.content}</span>`;
      }
    }
  });
  