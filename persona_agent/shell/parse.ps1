# Reads PowerShell commands for Mibo with PowerShell's own parser and parameter binder.
# One request a line on stdin: {"b64": <UTF-8 command, base64>, "cwd": <folder>}; one JSON answer a line.
# It only parses, binds and looks commands up; it never runs what it reads.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8
[Console]::InputEncoding = $utf8
$A = 'System.Management.Automation.Language.'
# Looking a name up can import the module that has it and run its code: only Windows' own module folders.
$env:PSModulePath = "$env:ProgramFiles\WindowsPowerShell\Modules;$PSHOME\Modules"
# Variables whose value is the same here as in the command's own PowerShell.
$Known = @('HOME', 'PWD', 'PSHOME', 'true', 'false', 'null')

function Test-Simple($name) {
  return ($Known -contains $name) -or $name -like 'env:*'
}

function Get-El($e) {
  if ($null -eq $e) { return $null }
  $type = $e.GetType().Name
  if ($type -eq 'StringConstantExpressionAst') { return @{ k = 's'; v = $e.Value } }
  if ($type -eq 'ExpandableStringExpressionAst') {
    $simple = $true
    foreach ($n in $e.NestedExpressions) {
      if (-not ($n.GetType().Name -eq 'VariableExpressionAst' -and (Test-Simple $n.VariablePath.UserPath))) { $simple = $false }
    }
    if ($simple) { return @{ k = 's'; v = $ExecutionContext.InvokeCommand.ExpandString($e.Value); x = 1 } }
    return @{ k = 'o'; t = $e.Extent.Text; vars = @($e.NestedExpressions | ForEach-Object { $_.Extent.Text }) }
  }
  if ($type -eq 'ConstantExpressionAst') { return @{ k = 'n'; v = "$($e.Value)" } }
  if ($type -eq 'VariableExpressionAst') {
    $name = $e.VariablePath.UserPath
    if (Test-Simple $name) {
      $value = if ($name -like 'env:*') { [Environment]::GetEnvironmentVariable($name.Substring(4)) } else { Get-Variable -Name $name -ValueOnly -ErrorAction SilentlyContinue }
      return @{ k = 's'; v = "$value"; x = 1; var = $name }
    }
    return @{ k = 'v'; v = $name; sp = [bool]$e.Splatted }
  }
  if ($type -eq 'ArrayLiteralAst') { return @{ k = 'a'; items = @($e.Elements | ForEach-Object { Get-El $_ }) } }
  if ($type -eq 'CommandParameterAst') { return @{ k = 'p'; v = $e.ParameterName } }
  if ($type -eq 'ParenExpressionAst' -and $e.Pipeline.GetType().Name -eq 'PipelineAst' -and $e.Pipeline.PipelineElements.Count -eq 1 -and $e.Pipeline.PipelineElements[0].GetType().Name -eq 'CommandExpressionAst') {
    return Get-El $e.Pipeline.PipelineElements[0].Expression
  }
  return @{ k = 'o'; t = $e.Extent.Text; type = $type }
}

function Get-Resolved($name) {
  if (-not $name) { return $null }
  try { $ci = $ExecutionContext.InvokeCommand.GetCommand($name, 'All') } catch { $ci = $null }
  $hops = 0
  while ($ci -and "$($ci.CommandType)" -eq 'Alias' -and $hops -lt 8) { $ci = $ci.ResolvedCommand; $hops++ }
  if (-not $ci) { return $null }
  $path = ''
  if ("$($ci.CommandType)" -in @('Application', 'ExternalScript')) { $path = $ci.Path }
  return @{ ct = "$($ci.CommandType)"; n = $ci.Name; m = "$($ci.ModuleName)"; path = $path }
}

function Read-Source($src, $cwd) {
  $tokens = $null; $errors = $null
  $ast = [System.Management.Automation.Language.Parser]::ParseInput($src, [ref]$tokens, [ref]$errors)
  $nodes = New-Object System.Collections.ArrayList
  $vars = @{}
  if ($cwd -and (Test-Path -LiteralPath $cwd)) { Set-Location -LiteralPath $cwd }
  foreach ($n in $ast.FindAll({ $true }, $true)) {
    $type = $n.GetType().Name
    $off = $n.Extent.StartOffset
    if ($type -eq 'CommandAst') {
      $name = $n.GetCommandName()
      $bound = @{}
      $unbound = @()
      try {
        $b = [System.Management.Automation.Language.StaticParameterBinder]::BindCommand($n, $true)
        foreach ($key in $b.BoundParameters.Keys) {
          $bp = $b.BoundParameters[$key]
          $bound[$key] = @{ el = (Get-El $bp.Value); cv = "$($bp.ConstantValue)" }
        }
        $unbound = @($b.BindingExceptions.Keys)
      } catch { $unbound = @('?') }
      $redirs = @($n.Redirections | Where-Object { $_.GetType().Name -eq 'FileRedirectionAst' } | ForEach-Object {
        @{ append = [bool]$_.Append; file = (Get-El $_.Location) } })
      $pipe = $n.Parent
      $index = if ($pipe.GetType().Name -eq 'PipelineAst') { $pipe.PipelineElements.IndexOf($n) } else { 0 }
      $inside = $false
      $up = $n.Parent
      while ($up) { if ($up.GetType().Name -eq 'ScriptBlockExpressionAst') { $inside = $true; break }; $up = $up.Parent }
      [void]$nodes.Add(@{ type = 'cmd'; off = $off; name = $name; op = "$($n.InvocationOperator)";
        first = (Get-El $n.CommandElements[0]); res = (Get-Resolved $name); bound = $bound; unbound = $unbound;
        args = @($n.CommandElements | Select-Object -Skip 1 | ForEach-Object { Get-El $_ });
        redirs = $redirs; pipe = $pipe.Extent.StartOffset; index = $index; inblock = $inside; text = $n.Extent.Text })
    } elseif ($type -eq 'CommandExpressionAst') {
      $redirs = @($n.Redirections | Where-Object { $_.GetType().Name -eq 'FileRedirectionAst' } | ForEach-Object {
        @{ append = [bool]$_.Append; file = (Get-El $_.Location) } })
      if ($redirs.Count) { [void]$nodes.Add(@{ type = 'expr'; off = $off; redirs = $redirs }) }
    } elseif ($type -eq 'InvokeMemberExpressionAst') {
      $member = if ($n.Member.GetType().Name -eq 'StringConstantExpressionAst') { $n.Member.Value } else { '' }
      $on = if ($n.Expression.GetType().Name -eq 'TypeExpressionAst') { $n.Expression.TypeName.FullName } else { '' }
      # What it is called on: the kind of expression, and the member, variable or type that made it.
      $recv = $n.Expression
      while ($recv.GetType().Name -eq 'ParenExpressionAst' -and $recv.Pipeline.GetType().Name -eq 'PipelineAst' -and $recv.Pipeline.PipelineElements.Count -eq 1 -and $recv.Pipeline.PipelineElements[0].GetType().Name -eq 'CommandExpressionAst') { $recv = $recv.Pipeline.PipelineElements[0].Expression }
      $rname = ''
      if ($recv.GetType().Name -in @('MemberExpressionAst', 'InvokeMemberExpressionAst') -and $recv.Member.GetType().Name -eq 'StringConstantExpressionAst') { $rname = $recv.Member.Value }
      elseif ($recv.GetType().Name -eq 'VariableExpressionAst') { $rname = $recv.VariablePath.UserPath }
      elseif ($recv.GetType().Name -eq 'ConvertExpressionAst') { $rname = $recv.Type.TypeName.FullName }
      [void]$nodes.Add(@{ type = 'method'; off = $off; member = $member; static = [bool]$n.Static; on = $on; text = $n.Extent.Text;
        recv = $recv.GetType().Name; rname = $rname; args = @($n.Arguments | Select-Object -First 4 | ForEach-Object { Get-El $_ }); nargs = @($n.Arguments).Count })
    } elseif ($type -in @('TypeExpressionAst', 'TypeConstraintAst')) {
      [void]$nodes.Add(@{ type = 'type'; off = $off; name = $n.TypeName.FullName })
    } elseif ($type -eq 'AssignmentStatementAst') {
      $left = $n.Left
      while ($left.GetType().Name -in @('ConvertExpressionAst', 'AttributedExpressionAst')) { $left = $left.Child }
      $lname = if ($left.GetType().Name -eq 'VariableExpressionAst') { $left.VariablePath.UserPath } else { '' }
      $right = $null
      if ($n.Right.GetType().Name -eq 'CommandExpressionAst') { $right = Get-El $n.Right.Expression }
      elseif ($n.Right.GetType().Name -eq 'PipelineAst' -and $n.Right.PipelineElements.Count -eq 1 -and $n.Right.PipelineElements[0].GetType().Name -eq 'CommandExpressionAst') { $right = Get-El $n.Right.PipelineElements[0].Expression }
      [void]$nodes.Add(@{ type = 'assign'; off = $off; var = $lname; left = $n.Left.Extent.Text; op = "$($n.Operator)"; right = $right; ltype = $left.GetType().Name })
    } elseif ($type -eq 'VariableExpressionAst') {
      $vars[$n.VariablePath.UserPath] = 1
    } elseif ($type -eq 'FunctionDefinitionAst') {
      [void]$nodes.Add(@{ type = 'func'; off = $off; name = $n.Name })
    } elseif ($type -in @('UsingStatementAst', 'DynamicKeywordStatementAst', 'TypeDefinitionAst', 'DataStatementAst', 'TrapStatementAst')) {
      [void]$nodes.Add(@{ type = 'other'; off = $off; what = $type; text = $n.Extent.Text })
    } elseif ($type -eq 'ForEachStatementAst') {
      [void]$nodes.Add(@{ type = 'foreach'; off = $off; var = $n.Variable.VariablePath.UserPath })
    }
  }
  return @{ errors = @($errors | ForEach-Object { $_.Message }); nodes = $nodes; vars = @($vars.Keys) }
}

while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line) { break }
  try {
    $req = $line | ConvertFrom-Json
    $src = $utf8.GetString([Convert]::FromBase64String($req.b64))
    $out = Read-Source $src $req.cwd
  } catch {
    $out = @{ fatal = "$_" }
  }
  [Console]::Out.WriteLine(($out | ConvertTo-Json -Depth 14 -Compress))
  [Console]::Out.Flush()
}
